# Voca External API: thêm từ vựng từ service khác

Tài liệu này dành cho các ứng dụng muốn đẩy từ mới vào kho từ của một người dùng Voca, ví dụ app real-time caption, extension trình duyệt, chatbot, công cụ đọc tài liệu hay script import.

Bạn gửi một từ hoặc tối đa 100 từ mỗi request, kèm nghĩa và câu ngữ cảnh nếu có. Voca lưu từ vào kho của người dùng và tự đưa vào lịch ôn tập. Gửi lại một từ đã có sẽ không tạo bản trùng: Voca chỉ bổ sung những gì mới.

| Tài liệu | Nội dung |
|---|---|
| **README.md** (trang này) | Bắt đầu nhanh, khái niệm, giới hạn, xử lý lỗi |
| [reference.md](reference.md) | Chi tiết từng endpoint, trường dữ liệu, mã lỗi |
| [examples.md](examples.md) | curl, Python, JavaScript, extension trình duyệt, app phụ đề |
| [voca_client.py](voca_client.py) | Client Python một file, chỉ dùng thư viện chuẩn, chép vào project là dùng được |
| [OpenAPI spec](https://voca-zeta-five.vercel.app/static/openapi.yaml) | Đặc tả máy đọc được (OpenAPI 3.1), dùng để sinh client hoặc import vào Postman |

## Bắt đầu nhanh

**1. Lấy API key.** Đăng nhập Voca → **Cài đặt → Ứng dụng kết nối** → nhập tên ứng dụng → **+ Thêm ứng dụng**. Key có dạng `voca_1a2b3c4d_…` và **chỉ hiện một lần**, hãy lưu lại ngay.

**2. Gửi một từ.**

```bash
curl -X POST https://voca-zeta-five.vercel.app/api/v1/external/vocabulary \
  -H "X-API-Key: $VOCA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"word": "leverage", "translation": "tận dụng",
       "context": {"sentence": "Financial institutions leverage derivatives.", "source_title": "Quant book"}}'
```

```json
{"id": "7f0c…", "word": "leverage", "status": "created", "created": true,
 "sense_added": true, "context_added": true, "collection_added": true}
```

**3. Gửi nhiều từ.**

```bash
curl -X POST https://voca-zeta-five.vercel.app/api/v1/external/vocabulary/batch \
  -H "X-API-Key: $VOCA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source": "quant_reader",
       "items": ["hedge", {"word": "yield", "translation": "lợi suất"}]}'
```

```json
{"summary": {"created": 2, "updated": 0, "unchanged": 0, "failed": 0, "total": 2},
 "results": [{"index": 0, "word": "hedge", "status": "created", …},
             {"index": 1, "word": "yield", "status": "created", …}]}
```

Hoặc dùng client Python có sẵn:

```python
from voca_client import VocaClient

voca = VocaClient(api_key=os.environ["VOCA_API_KEY"])
voca.add_word("leverage", translation="tận dụng", context="Banks leverage capital.")
voca.add_words(["hedge", "yield", "spread"], source="quant_reader")  # tự chia lô 100 từ
```

## Khái niệm

### Base URL và xác thực

```
https://voca-zeta-five.vercel.app/api/v1
```

Mọi request gửi header `X-API-Key: <key>`. Mỗi key gắn với **một người dùng** và **một ứng dụng**: từ gửi lên luôn vào kho của người sở hữu key.

| Scope | Cho phép |
|---|---|
| `vocabulary:write` | `POST /external/vocabulary`, `POST /external/vocabulary/batch` |
| `vocabulary:read` | `GET /external/vocabulary/lookup`, `GET /external/collections` |

Key tạo từ giao diện có cả hai scope. Người dùng có thể thu hồi key bất cứ lúc nào; sau đó mọi request dùng key đó nhận `401`.

**Giữ key ở phía server** nếu có thể. Với extension hay app desktop, key nằm trên máy người dùng nên mỗi người dùng phải tự tạo key riêng cho mình. Không nhúng một key chung vào bản phát hành.

### Upsert: gửi lại không tạo trùng

Một từ được nhận diện theo **(người dùng, ngôn ngữ, từ)**. Khi so sánh, Voca không phân biệt hoa thường và bỏ khoảng trắng thừa, nên `"Leverage "` và `"leverage"` là cùng một từ.

| Tình huống | Voca làm gì | `status` |
|---|---|---|
| Từ chưa có | Tạo từ mới với nghĩa, ngữ cảnh, tag, rồi thêm vào bộ từ đích | `created` |
| Từ đã có, có thông tin mới | Thêm nghĩa mới (nếu khác các nghĩa đã có), ngữ cảnh mới, tag mới, hoặc thêm vào bộ từ đích | `updated` |
| Từ đã có, không có gì mới | Không đổi gì | `unchanged` |
| Dữ liệu sai | Không lưu gì | lỗi `4xx` (gửi đơn) hoặc `failed` (trong batch) |

Nhờ vậy **gửi lại luôn an toàn**: khi timeout hoặc gặp lỗi mạng, bạn cứ gửi lại request đó mà không lo tạo trùng.

Voca không bao giờ ghi đè hay xoá dữ liệu người dùng đã nhập, chỉ thêm vào. Phiên âm chỉ được điền khi từ chưa có phiên âm.

### Từ được lưu vào đâu

Bộ từ đích được chọn theo thứ tự ưu tiên:

1. `collection_id` của từng mục
2. `collection_id` cấp batch
3. Bộ từ mặc định đã chọn khi tạo ứng dụng trong Voca
4. **Hộp thư từ mới** (Inbox) của người dùng

Dùng `GET /external/collections` để lấy danh sách bộ từ mà key được phép ghi vào.

### Từ chưa có nghĩa

Chỉ `word` là bắt buộc. Từ gửi lên mà thiếu cả `translation` lẫn `meaning` sẽ được đánh dấu **chưa có nghĩa**; người dùng thấy nhắc bổ sung trong giao diện. Một lần gửi sau có kèm nghĩa sẽ tự điền vào.

Nên gửi kèm `translation` (nghĩa tiếng Việt), vì đây là thứ hiển thị trên thẻ học và dùng để tạo câu hỏi trắc nghiệm.

### Ngữ cảnh

`context` là câu nơi người dùng gặp từ, kèm nguồn. Đây là tính năng giúp nhớ lâu nhất, nên gửi kèm bất cứ khi nào có:

```json
"context": {"sentence": "Banks leverage capital.", "source_title": "Quant book", "location": "Chương 3", "url": "https://…"}
```

`source_title` gom các từ theo tài liệu: người dùng lọc được "mọi từ gặp trong Quant book". Hãy dùng tên nguồn **ổn định** (cùng một cuốn sách thì cùng một chuỗi).

### Ngôn ngữ

`language` là ngôn ngữ của từ, mặc định `en`. Hiện hỗ trợ: `en`, `vi`, `ja`, `ko`, `zh`, `fr`, `de`, `es` (danh sách đầy đủ: `GET /api/v1/languages`, không cần key). Gửi ngôn ngữ khác sẽ bị lỗi `VALIDATION_ERROR`.

## Giới hạn

| Giới hạn | Giá trị |
|---|---|
| Số mục mỗi batch | 1–100 |
| Kích thước body | 1 MB |
| `POST /external/vocabulary` | 120 request/phút/key |
| `POST /external/vocabulary/batch` | 30 request/phút/key (tức tối đa khoảng 3.000 từ/phút) |
| `GET /external/vocabulary/lookup` | 300 request/phút/key |
| `GET /external/collections` | 60 request/phút/key |
| Thời gian tối đa mỗi request | 30 giây |

Mỗi response có header `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`. Vượt giới hạn sẽ nhận `429` kèm header `Retry-After` (số giây). Giới hạn được đếm trên từng instance serverless nên chỉ gần đúng; đừng dựa vào nó để điều tiết chính xác.

Một batch 100 từ thường mất vài giây. Hãy đặt timeout phía client khoảng **30 giây**.

## Lỗi

Mọi lỗi có chung một dạng:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "Dữ liệu không hợp lệ",
           "details": [{"field": "word", "message": "String should have at least 1 character"}]},
 "request_id": "3d9d36a8…"}
```

| HTTP | `code` | Nguyên nhân | Nên làm |
|---|---|---|---|
| 401 | `UNAUTHORIZED` | Thiếu key, key sai, đã thu hồi hoặc tài khoản bị khoá | Không gửi lại; báo người dùng tạo key mới |
| 403 | `FORBIDDEN` | Key thiếu scope cần thiết | Tạo key có đủ scope |
| 404 | `NOT_FOUND` | `collection_id` không tồn tại hoặc không có quyền ghi | Lấy lại danh sách qua `GET /external/collections` |
| 413 | `REQUEST_ENTITY_TOO_LARGE` | Body vượt 1 MB | Chia nhỏ batch |
| 422 | `VALIDATION_ERROR` | Dữ liệu sai (xem `details`) | Sửa dữ liệu; không gửi lại nguyên xi |
| 429 | `TOO_MANY_REQUESTS` | Vượt giới hạn tần suất | Chờ `Retry-After` giây rồi gửi lại |
| 5xx | `INTERNAL_ERROR` | Lỗi phía Voca | Gửi lại với backoff (1s, 2s, 4s…) |

Trong **batch**, lỗi của từng mục nằm trong `results[i].error` với cùng các `code` như trên, và HTTP status vẫn là `200`. Batch chỉ trả lỗi toàn cục (`401`, `403`, `413`, `422`, `429`) khi cả request không hợp lệ, ví dụ `items` rỗng hoặc hơn 100 mục.

Khi báo lỗi cho người phát triển Voca, gửi kèm `request_id`.

## Nên làm

- **Gom từ lại rồi gửi batch** thay vì gọi từng từ. Ví dụ app phụ đề nên gom trong vài giây hoặc tới khi đủ 20–50 từ.
- **Gửi `source`** (tên ứng dụng hoặc tính năng, như `"realtime_caption"`) cùng `context`, để người dùng thấy câu đó đến từ đâu. Mọi từ gửi qua API đều được đánh dấu là từ nguồn ngoài.
- **Gửi lại khi gặp 429, 5xx hoặc lỗi mạng**, có backoff. Nhờ cơ chế upsert, việc gửi lại không tạo trùng. `voca_client.py` đã làm sẵn phần này.
- **Không gửi lại khi gặp 4xx khác 429**: dữ liệu hoặc key có vấn đề.
- **Kiểm tra `results[i].status`** sau mỗi batch và ghi log các mục `failed`.
- Dùng `lookup` nếu cần hiện trạng thái "đã lưu" trong giao diện của bạn. Không cần gọi `lookup` trước khi gửi, vì upsert đã xử lý trùng.
