# Voca

Ứng dụng học và ghi nhớ từ vựng bằng **lặp lại ngắt quãng** (spaced repetition, SM-2 rút gọn) cho người Việt học tiếng Anh, thiết kế để mở rộng sang nhiều ngôn ngữ.

- **Backend:** Flask 3 (monolith chia module), SQLAlchemy 2, Alembic
- **Giao diện:** Jinja + HTMX + Alpine.js, tiếng Việt, dùng tốt trên điện thoại, có dark mode
- **Database:** SQLite khi chạy local, Turso (libSQL) trên production
- **Deploy:** Vercel (Python serverless)

Thiết kế chi tiết (ERD, API, thuật toán): [docs/DESIGN.md](docs/DESIGN.md).

## Tính năng

| Nhóm | Tính năng |
|---|---|
| Tài khoản | Đăng ký, đăng nhập, JWT (cookie httpOnly cho web, Bearer cho app), refresh token có rotation và phát hiện dùng lại, đổi mật khẩu, múi giờ, mục tiêu học |
| Từ vựng | Nhiều nghĩa cho một từ (loại từ, định nghĩa, bản dịch, đồng/trái nghĩa, ví dụ), phiên âm, CEFR, thẻ, ghi chú, **ngữ cảnh**: câu gốc + nguồn + vị trí |
| Tìm kiếm | Theo từ hoặc nghĩa, lọc theo trạng thái, bộ từ, thẻ, nguồn; sắp xếp |
| Bộ từ | Lồng nhau, “Hộp thư từ mới” mặc định, chia sẻ riêng tư/chia sẻ/công khai, vai trò người xem/biên tập, link mời, tham gia bộ công khai |
| Học | Bấm **Bắt đầu học** ở từng bộ từ để lên lịch (chọn số từ mới mỗi ngày); bộ chưa bắt đầu thì chưa học. Nút **Học hôm nay** theo từng bộ. **Lịch học** theo ngày: từ nào, của bộ nào, ôn hay mới. Flashcard, trắc nghiệm, gõ từ, phím tắt, “Tôi đã biết”, tạm ngưng, học lại |
| Thống kê | Mục tiêu ngày, độ chính xác, chuỗi ngày học, phân bố trạng thái, lịch hoạt động 12 tháng |
| API ngoài | API key cho từng ứng dụng (extension, app phụ đề, chatbot), thêm một hoặc nhiều từ (tối đa 100/request) kiểu upsert: từ đã có thì chỉ bổ sung nghĩa, ngữ cảnh, tag mới |

## Chạy ở máy local

Cần Python 3.12+. Không cần Docker hay database server.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # rồi đặt SECRET_KEY, JWT_SECRET_KEY
flask db upgrade                # tạo instance/voca.db và seed ngôn ngữ
python run.py                   # http://127.0.0.1:5000
```

Chạy test:

```bash
pytest
```

## Deploy lên Vercel + Turso

1. **Tạo database:** trong Vercel project, vào *Storage → Marketplace → Turso* và tạo database. Integration sẽ thêm `TURSO_DATABASE_URL` và `TURSO_AUTH_TOKEN` vào Environment Variables. Nếu tên biến khác, đổi lại cho khớp hai tên này.
2. **Thêm biến môi trường** trong Vercel:
   - `APP_ENV=production`
   - `SECRET_KEY`, `JWT_SECRET_KEY`: tạo bằng `python -c "import secrets; print(secrets.token_urlsafe(48))"`
3. **Tạo bảng trên Turso** từ máy bạn (migration không tự chạy trên Vercel):
   ```bash
   # đặt tạm 2 biến TURSO_* (lấy từ Vercel) trong .env rồi:
   flask db upgrade
   ```
4. **Deploy:** push lên nhánh `main` (repo đã nối với Vercel nên tự deploy), hoặc chạy `vercel deploy --prod`.
5. Kiểm tra `https://<domain>/healthz` trả về `{"status": "ok"}`.

Lưu ý khi deploy:

- Vercel cài thư viện từ `pyproject.toml` (không đọc `requirements.txt`). Thêm thư viện mới thì sửa cả hai file.
- Entrypoint được khai báo trong `[tool.vercel]` của `pyproject.toml` (`api.index:app`). Function chạy ở Tokyo (`hnd1`), cùng vùng với database.
- File tĩnh nằm ở `public/static`: trên Vercel CDN phục vụ trực tiếp, ở local Flask phục vụ.

Mỗi lần đổi model thì chạy `flask db migrate -m "..."` ở local, kiểm tra file sinh ra trong `migrations/versions/`, rồi `flask db upgrade` cho cả local và Turso.

## Gửi từ từ ứng dụng khác

Các service khác (app phụ đề, extension, chatbot, script import) thêm được một hoặc nhiều từ qua External API bằng API key tạo trong **Cài đặt → Ứng dụng kết nối**:

- `POST /api/v1/external/vocabulary`: một từ
- `POST /api/v1/external/vocabulary/batch`: tối đa 100 từ mỗi request, từng mục thành công hoặc thất bại độc lập
- Gửi lại không tạo trùng: từ đã có chỉ được bổ sung nghĩa, ngữ cảnh, tag mới

Tài liệu cho người tích hợp: [docs/external-api/](docs/external-api/README.md), gồm hướng dẫn, tham chiếu, ví dụ, client Python [voca_client.py](docs/external-api/voca_client.py) và [OpenAPI spec](public/static/openapi.yaml) (trên production: `/static/openapi.yaml`).

## Cấu trúc thư mục

```
api/index.py            entry cho Vercel
public/static/          CSS, JS, favicon
app/
  core/                 config dùng chung: DB types, lỗi, log, text, múi giờ, dialect libSQL
  ports/                interface cho storage và AI enrichment (implement sau)
  modules/
    auth/               tài khoản, JWT, refresh token
    vocabulary/         từ, nghĩa, ví dụ, ngữ cảnh, nguồn, thẻ
    collections/        bộ từ, chia sẻ, phân quyền (access.py)
    learning/engine/    SRS thuần Python: SM-2, chấm điểm (không phụ thuộc Flask/DB)
    learning/           hàng đợi ôn, chấm bài, trạng thái thẻ
    stats/              số liệu dashboard, streak, lịch hoạt động
    external/           ứng dụng ngoài, API key, endpoint thu thập từ
  web/                  trang Jinja (templates)
migrations/             Alembic
tests/                  unit (engine) + integration (API, web, driver libSQL)
```

## REST API (tóm tắt)

Tiền tố `/api/v1`. Xác thực bằng `Authorization: Bearer <access_token>`, lấy qua `POST /auth/login`.

| | |
|---|---|
| Auth | `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout` · `GET/PATCH /me` · `POST /me/password` |
| Từ vựng | `GET/POST /words` · `GET/PUT/DELETE /words/{id}` · `POST /words/{id}/contexts` · `POST /words/{id}/known\|suspend\|unsuspend\|reset` · `GET /tags` · `GET/POST /sources` · `GET /languages` |
| Bộ từ | `GET/POST /collections` · `GET/PATCH/DELETE /collections/{id}` · `POST /collections/{id}/words` · `DELETE /collections/{id}/words/{word_id}` · `POST /collections/{id}/share\|share-link\|join\|leave` · `GET /collections/{id}/members` · `PATCH/DELETE /collections/{id}/members/{user_id}` |
| Học | `GET /reviews/today?mode=flashcard\|mcq\|typing&collection_id=` · `GET /reviews/summary` · `POST /reviews/{word_id}/result` |
| Kế hoạch học | `POST/GET/PATCH/DELETE /collections/{id}/study` (bắt đầu, xem, đổi số từ mới/ngày hoặc tạm dừng, bỏ) · `GET /study/plans` · `GET /study/calendar?days=14&collection_id=` |
| Thống kê | `GET /stats/today` · `/stats/overview` · `/stats/calendar` |
| Ứng dụng ngoài | `GET/POST /external/applications` · `DELETE /external/applications/{id}` · `POST /external/applications/{id}/keys` · `DELETE /external/keys/{id}` · (API key) `POST /external/vocabulary` · `POST /external/vocabulary/batch` · `GET /external/vocabulary/lookup` · `GET /external/collections` |

Mọi lỗi có chung một dạng: `{"error": {"code": "...", "message": "...", "details": ...}, "request_id": "..."}`.
