# Voca External API: tham chiếu

Base URL: `https://voca-zeta-five.vercel.app/api/v1` · Xác thực: header `X-API-Key` · Body: JSON UTF-8.
Khái niệm chung (upsert, bộ từ đích, giới hạn, lỗi): xem [README.md](README.md).

| Method | Path | Scope | Mô tả |
|---|---|---|---|
| POST | `/external/vocabulary` | `vocabulary:write` | Thêm hoặc cập nhật một từ |
| POST | `/external/vocabulary/batch` | `vocabulary:write` | Thêm hoặc cập nhật tối đa 100 từ |
| GET | `/external/vocabulary/lookup` | `vocabulary:read` | Kiểm tra một từ đã có trong kho chưa |
| GET | `/external/collections` | `vocabulary:read` | Danh sách bộ từ có thể ghi vào |
| GET | `/languages` | không cần | Danh sách ngôn ngữ được hỗ trợ |

Mọi endpoint `/external/*` đều mở CORS (`Access-Control-Allow-Origin: *`), nên extension và trang web gọi thẳng được.

---

## Đối tượng `WordInput`

Dùng cho `POST /external/vocabulary` và cho từng mục của batch.

| Trường | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `word` | string, 1–200 ký tự | **có** | Từ hoặc cụm từ. Khoảng trắng thừa bị bỏ. |
| `language` | string | không | Mã ngôn ngữ của từ. Mặc định `en`. Hỗ trợ: `en vi ja ko zh fr de es`. |
| `translation` | string, ≤ 1000 | không | Nghĩa bằng tiếng mẹ đẻ của người học, ví dụ `"đòn bẩy"`. Hiển thị trên thẻ học. |
| `translation_language` | string | không | Ngôn ngữ của `translation`. Mặc định là tiếng mẹ đẻ của người dùng (`vi`). |
| `meaning` | string, ≤ 2000 | không | Định nghĩa bằng chính ngôn ngữ của từ, ví dụ `"use something to maximum advantage"`. |
| `part_of_speech` | string, ≤ 30 | không | Loại từ: `noun`, `verb`, `adjective`, `adverb`, `phrase`, `phrasal verb`, `idiom`… |
| `phonetic` | string, ≤ 200 | không | Phiên âm, ví dụ `"/ˈlev.ər.ɪdʒ/"`. Chỉ được dùng khi từ chưa có phiên âm. |
| `tags` | string[], ≤ 20 | không | Thẻ, ví dụ `["IELTS", "Finance"]`. Tag mới được thêm vào, tag cũ giữ nguyên. |
| `context` | `Context` hoặc string | không | Câu nơi gặp từ. Truyền chuỗi thì chuỗi đó được hiểu là `context.sentence`. |
| `source` | string, ≤ 64 | không | Tên ứng dụng hoặc tính năng gửi từ. Được lưu cùng `context` và hiển thị là "qua …" dưới câu ngữ cảnh. Mặc định là tên ứng dụng đã đăng ký. |
| `collection_id` | string | không | Bộ từ đích. Xem thứ tự ưu tiên trong README. |

`translation` và `meaning` tạo thành **một nghĩa**. Nếu từ đã có một nghĩa trùng `translation` (hoặc trùng `meaning`, không phân biệt hoa thường), nghĩa đó không được thêm lần nữa.

### Đối tượng `Context`

| Trường | Kiểu | Mô tả |
|---|---|---|
| `sentence` | string, ≤ 2000 | Câu gốc chứa từ |
| `translation` | string, ≤ 2000 | Bản dịch câu |
| `source_title` | string, ≤ 255 | Tên nguồn: sách, bài báo, video, podcast… Nguồn cùng tên (không phân biệt hoa thường) được gom chung. |
| `source_type` | enum | `book`, `article`, `video`, `caption`, `chat`, `course`, `other`. Chỉ dùng khi tạo nguồn mới. |
| `location` | string, ≤ 255 | Vị trí trong nguồn: `"Chương 3"`, `"p.42"`, `"12:35"` |
| `url` | string, ≤ 1000 | Liên kết tới nguồn |

Ngữ cảnh phải có ít nhất một trong `sentence`, `source_title` hoặc `url`. Ngữ cảnh bị coi là trùng (và không thêm) khi:
- có `sentence` và từ đã có ngữ cảnh cùng câu đó (không phân biệt hoa thường, khoảng trắng); hoặc
- không có `sentence` và từ đã có ngữ cảnh không câu với cùng `source_title`, `url`, `location`.

---

## POST `/external/vocabulary`

Thêm hoặc cập nhật **một** từ. Body là một `WordInput`.

```http
POST /api/v1/external/vocabulary
X-API-Key: voca_1a2b3c4d_…
Content-Type: application/json

{
  "word": "leverage",
  "translation": "tận dụng",
  "meaning": "use something to maximum advantage",
  "part_of_speech": "verb",
  "tags": ["Finance"],
  "context": {
    "sentence": "Financial institutions leverage derivatives to hedge risk.",
    "source_title": "Quant book",
    "source_type": "book",
    "location": "Chương 3"
  },
  "source": "quant_reader"
}
```

**Response**: `201 Created` khi tạo mới, `200 OK` khi từ đã có.

```json
{
  "id": "7f0c2a4e-…",
  "word": "leverage",
  "status": "created",
  "created": true,
  "sense_added": true,
  "context_added": true,
  "collection_added": true
}
```

| Trường | Mô tả |
|---|---|
| `id` | ID của từ trong Voca |
| `word` | Từ như đang lưu (giữ cách viết của lần tạo đầu tiên) |
| `status` | `created`, `updated` hoặc `unchanged` |
| `created` | `true` nếu vừa tạo mới (tương đương `status == "created"`) |
| `sense_added` | Có thêm nghĩa mới không |
| `context_added` | Có thêm ngữ cảnh mới không |
| `collection_added` | Từ có vừa được thêm vào bộ từ đích không |

**Lỗi**: `401`, `403`, `404` (`collection_id` không hợp lệ), `422`, `429`.

---

## POST `/external/vocabulary/batch`

Thêm hoặc cập nhật **1–100** từ. Mỗi mục được xử lý **độc lập** và lưu ngay khi xong: mục lỗi không ảnh hưởng mục khác, và các mục thành công vẫn được lưu kể cả khi có mục lỗi.

| Trường | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `items` | (`WordInput` \| string)[], 1–100 | **có** | Các từ cần import. Một chuỗi được hiểu là `{"word": "<chuỗi>"}`. |
| `language` | string | không | Mặc định cho mọi mục |
| `translation_language` | string | không | Mặc định cho mọi mục |
| `source` | string | không | Mặc định cho mọi mục |
| `collection_id` | string | không | Mặc định cho mọi mục |
| `tags` | string[] | không | Mặc định cho mọi mục |

Giá trị cấp batch chỉ áp dụng cho mục **không tự đặt** trường đó; không gộp chung. Ví dụ mục có `"tags": ["A"]` và batch có `"tags": ["B"]` thì mục đó chỉ nhận `["A"]`.

Các mục được xử lý theo đúng thứ tự gửi lên. Nếu một từ xuất hiện hai lần trong batch, lần sau được gộp vào lần trước.

```http
POST /api/v1/external/vocabulary/batch
X-API-Key: voca_1a2b3c4d_…
Content-Type: application/json

{
  "source": "realtime_caption",
  "tags": ["Podcast"],
  "items": [
    {"word": "serendipity", "translation": "sự tình cờ may mắn",
     "context": {"sentence": "It was pure serendipity.", "source_title": "Lex Fridman #412", "location": "01:12:05"}},
    "ubiquitous",
    {"word": "", "translation": "lỗi"}
  ]
}
```

**Response**: `200 OK` nếu request hợp lệ, kể cả khi có mục lỗi.

```json
{
  "summary": {"created": 2, "updated": 0, "unchanged": 0, "failed": 1, "total": 3},
  "results": [
    {"index": 0, "id": "…", "word": "serendipity", "status": "created", "created": true,
     "sense_added": true, "context_added": true, "collection_added": true},
    {"index": 1, "id": "…", "word": "ubiquitous", "status": "created", "created": true,
     "sense_added": false, "context_added": false, "collection_added": true},
    {"index": 2, "word": "", "status": "failed",
     "error": {"code": "VALIDATION_ERROR", "message": "Dữ liệu không hợp lệ",
               "details": [{"field": "word", "message": "String should have at least 1 character"}]}}
  ]
}
```

- `results` có đúng một phần tử cho mỗi mục, cùng thứ tự; `index` là vị trí trong `items`.
- Mục thành công có các trường như response của endpoint gửi đơn.
- Mục `failed` có `error` (`code`, `message`, có thể có `details`) và không có `id`.
- `summary.total` = số mục; tổng bốn trạng thái luôn bằng `total`.

**Lỗi toàn cục**: `401`, `403`, `413`, `422` (`items` rỗng, hơn 100 mục, hoặc không phải mảng), `429`.

---

## GET `/external/vocabulary/lookup`

Kiểm tra một từ đã có trong kho của người dùng chưa. So sánh không phân biệt hoa thường.

| Query | Mô tả |
|---|---|
| `word` | Từ cần tìm (bắt buộc; bỏ trống thì luôn trả `found: false`) |
| `language` | Mặc định `en` |

```http
GET /api/v1/external/vocabulary/lookup?word=Leverage&language=en
X-API-Key: voca_1a2b3c4d_…
```

```json
{"found": true, "id": "7f0c2a4e-…", "word": "leverage", "meaning": "tận dụng"}
```

```json
{"found": false}
```

`meaning` là nghĩa chính: bản dịch đầu tiên, nếu không có thì là định nghĩa đầu tiên, nếu không có nữa thì chuỗi rỗng.

---

## GET `/external/collections`

Các bộ từ mà người sở hữu key có thể ghi vào: bộ của chính họ và bộ được chia sẻ với quyền biên tập.

```json
{
  "items": [
    {"id": "…", "name": "Hộp thư từ mới", "parent_id": null, "is_inbox": true, "role": "owner", "word_count": 42},
    {"id": "…", "name": "IELTS", "parent_id": null, "is_inbox": false, "role": "owner", "word_count": 310},
    {"id": "…", "name": "Academic words", "parent_id": "…", "is_inbox": false, "role": "owner", "word_count": 120},
    {"id": "…", "name": "Lớp cô Lan", "parent_id": null, "is_inbox": false, "role": "editor", "word_count": 95}
  ]
}
```

Bộ từ có thể lồng nhau (`parent_id`). Các bộ của người dùng được liệt kê theo thứ tự cây (bộ cha trước bộ con).

---

## GET `/languages`

Không cần API key.

```json
{"items": [{"code": "zh", "name": "Chinese", "native_name": "中文"},
           {"code": "en", "name": "English", "native_name": "English"}, …]}
```

---

## Header

| Header | Chiều | Mô tả |
|---|---|---|
| `X-API-Key` | request | API key, bắt buộc với `/external/*` |
| `Content-Type: application/json` | request | Bắt buộc với `POST` |
| `X-Request-ID` | request/response | Tuỳ chọn gửi lên để truy vết; Voca luôn trả lại một giá trị |
| `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` | response | Trạng thái giới hạn tần suất |
| `Retry-After` | response (429) | Số giây nên chờ trước khi gửi lại |

## Mã lỗi

| HTTP | `code` | Khi nào |
|---|---|---|
| 401 | `UNAUTHORIZED` | Thiếu/sai key, key bị thu hồi hoặc hết hạn, tài khoản không khả dụng |
| 403 | `FORBIDDEN` | Key thiếu scope |
| 404 | `NOT_FOUND` | `collection_id` không tồn tại hoặc không có quyền ghi |
| 405 | `METHOD_NOT_ALLOWED` | Sai HTTP method |
| 413 | `REQUEST_ENTITY_TOO_LARGE` | Body lớn hơn 1 MB |
| 422 | `VALIDATION_ERROR` | Dữ liệu không hợp lệ; `details` là danh sách `{field, message}` hoặc chỉ có `message` (ví dụ ngôn ngữ chưa hỗ trợ) |
| 429 | `TOO_MANY_REQUESTS` | Vượt giới hạn tần suất |
| 500 | `INTERNAL_ERROR` | Lỗi phía Voca |
