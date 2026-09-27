# Voca External API: ví dụ

Các ví dụ dùng biến môi trường `VOCA_API_KEY` và base URL production. Chi tiết trường dữ liệu: [reference.md](reference.md).

- [curl](#curl)
- [Python: client có sẵn](#python-client-có-sẵn)
- [Python: app phụ đề gom từ rồi gửi theo lô](#python-app-phụ-đề-gom-từ-rồi-gửi-theo-lô)
- [Python: import từ file CSV](#python-import-từ-file-csv)
- [JavaScript / TypeScript](#javascript--typescript)
- [Extension trình duyệt (Manifest V3)](#extension-trình-duyệt-manifest-v3)

---

## curl

```bash
export VOCA=https://voca-zeta-five.vercel.app/api/v1
export VOCA_API_KEY=voca_1a2b3c4d_...

# Một từ, chỉ có từ (nghĩa sẽ được bổ sung sau)
curl -X POST $VOCA/external/vocabulary -H "X-API-Key: $VOCA_API_KEY" -H "Content-Type: application/json" \
  -d '{"word": "ubiquitous"}'

# Một từ đầy đủ
curl -X POST $VOCA/external/vocabulary -H "X-API-Key: $VOCA_API_KEY" -H "Content-Type: application/json" \
  -d '{"word": "abandon", "translation": "từ bỏ", "meaning": "to stop doing something",
       "part_of_speech": "verb", "phonetic": "/əˈbændən/", "tags": ["IELTS"],
       "context": {"sentence": "They abandoned the plan.", "source_title": "Cambridge IELTS 18", "location": "Test 2"}}'

# Nhiều từ vào một bộ từ cụ thể
curl -X POST $VOCA/external/vocabulary/batch -H "X-API-Key: $VOCA_API_KEY" -H "Content-Type: application/json" \
  -d '{"collection_id": "<id>", "source": "import_script", "items": ["hedge", "yield", "spread"]}'

# Kiểm tra từ đã lưu chưa
curl "$VOCA/external/vocabulary/lookup?word=abandon" -H "X-API-Key: $VOCA_API_KEY"

# Các bộ từ có thể ghi vào
curl $VOCA/external/collections -H "X-API-Key: $VOCA_API_KEY"
```

---

## Python: client có sẵn

Chép [voca_client.py](voca_client.py) vào project. Client chỉ dùng thư viện chuẩn, tự gửi lại khi gặp `429`/`5xx`/lỗi mạng, và tự chia lô 100 từ.

```python
import os
from voca_client import VocaClient, VocaError

voca = VocaClient(api_key=os.environ["VOCA_API_KEY"])

# Một từ
result = voca.add_word(
    "leverage",
    translation="tận dụng",
    part_of_speech="verb",
    context={"sentence": "Banks leverage capital.", "source_title": "Quant book", "location": "Chương 3"},
    source="quant_reader",
)
print(result["status"])  # created | updated | unchanged

# Nhiều từ: bao nhiêu cũng được, client tự chia lô 100
report = voca.add_words(
    ["hedge", {"word": "yield", "translation": "lợi suất"}, {"word": "spread", "tags": ["Bond"]}],
    source="quant_reader",
    tags=["Quant"],          # áp dụng cho mục không tự đặt tags
)
print(report["summary"])     # {'created': 3, 'updated': 0, 'unchanged': 0, 'failed': 0, 'total': 3}
for r in report["results"]:
    if r["status"] == "failed":
        print(f"#{r['index']} {r['word']!r}: {r['error']['message']}")

# Chọn bộ từ đích theo tên
target = next(c for c in voca.collections() if c["name"] == "IELTS")
voca.add_words(["cohesion", "coherence"], collection_id=target["id"])

# Xử lý lỗi
try:
    voca.add_word("chat", language="xx")
except VocaError as err:
    print(err.status, err.code, err.message)  # 422 VALIDATION_ERROR Ngôn ngữ 'xx' chưa được hỗ trợ
```

---

## Python: app phụ đề gom từ rồi gửi theo lô

App real-time caption có thể gặp nhiều từ mới mỗi phút. Thay vì gọi API cho từng từ, hãy gom lại và gửi một batch khi đủ số lượng hoặc sau vài giây. Khi Voca tạm thời lỗi, các từ được giữ lại để gửi lần sau.

```python
import threading
import time

from voca_client import VocaClient, VocaError


class VocaSink:
    """Collects captured words and sends them to Voca in batches from a background thread."""

    def __init__(self, client: VocaClient, source: str = "realtime_caption",
                 max_batch: int = 50, max_wait: float = 5.0):
        self.client = client
        self.source = source
        self.max_batch = max_batch
        self.max_wait = max_wait
        self._items: list[dict] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def add(self, word: str, sentence: str | None = None, translation: str | None = None,
            source_title: str | None = None, location: str | None = None) -> None:
        item: dict = {"word": word}
        if translation:
            item["translation"] = translation
        if sentence or source_title:
            item["context"] = {"sentence": sentence, "source_title": source_title, "location": location}
        with self._lock:
            self._items.append(item)
            if len(self._items) >= self.max_batch:
                self._wake.set()

    def close(self) -> None:
        """Sends whatever is left, then stops the thread."""
        self._stop.set()
        self._wake.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.max_wait)
            self._wake.clear()
            self._flush()
        self._flush()

    def _flush(self) -> None:
        with self._lock:
            batch, self._items = self._items[:100], self._items[100:]
        if not batch:
            return
        try:
            report = self.client.add_words(batch, source=self.source)
        except VocaError as err:
            if err.status in (0, 429) or err.status >= 500:
                with self._lock:  # temporary problem: keep the words for the next round
                    self._items = batch + self._items
                return
            print(f"Voca rejected the batch: {err}")  # 401/403/422: do not retry
            return
        for r in report["results"]:
            if r["status"] == "failed":
                print(f"Voca skipped {r['word']!r}: {r['error']['message']}")


# Cách dùng trong app phụ đề:
# sink = VocaSink(VocaClient(api_key=...))
# sink.add("serendipity", sentence="It was pure serendipity.", translation="sự tình cờ may mắn",
#          source_title="Lex Fridman #412", location="01:12:05")
# ...
# sink.close()   # khi thoát app
```

---

## Python: import từ file CSV

File `words.csv` (UTF-8, có dòng tiêu đề):

```csv
word,translation,part_of_speech,example,tags
abandon,từ bỏ,verb,They abandoned the plan.,IELTS
leverage,đòn bẩy,noun,Leverage magnifies returns.,Finance;Quant
```

```python
import csv
import os
import sys

from voca_client import VocaClient

voca = VocaClient(api_key=os.environ["VOCA_API_KEY"])

with open(sys.argv[1], encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

items = []
for row in rows:
    item = {"word": row["word"].strip()}
    if row.get("translation"):
        item["translation"] = row["translation"].strip()
    if row.get("part_of_speech"):
        item["part_of_speech"] = row["part_of_speech"].strip()
    if row.get("example"):
        item["context"] = {"sentence": row["example"].strip(), "source_title": os.path.basename(sys.argv[1])}
    if row.get("tags"):
        item["tags"] = [t.strip() for t in row["tags"].split(";") if t.strip()]
    items.append(item)

report = voca.add_words(items, source="csv_import")
print(report["summary"])
for r in report["results"]:
    if r["status"] == "failed":
        print(f"dòng {r['index'] + 2}: {r['word']!r} → {r['error']['message']}")
```

```bash
python import_csv.py words.csv
```

Chạy lại script với cùng file là an toàn: những từ đã có sẽ trả `unchanged`.

---

## JavaScript / TypeScript

Dùng được trong Node 18+, Deno, Bun và trình duyệt (đã mở CORS).

```ts
const VOCA = "https://voca-zeta-five.vercel.app/api/v1";

type WordInput = {
  word: string;
  language?: string;
  translation?: string;
  meaning?: string;
  part_of_speech?: string;
  phonetic?: string;
  tags?: string[];
  context?: string | { sentence?: string; source_title?: string; location?: string; url?: string };
  source?: string;
  collection_id?: string;
};

class VocaError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

async function voca<T>(apiKey: string, method: string, path: string, body?: unknown, retries = 3): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(VOCA + path, {
      method,
      headers: { "X-API-Key": apiKey, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.ok) return res.json() as Promise<T>;
    const data = await res.json().catch(() => ({}));
    const retryable = res.status === 429 || res.status >= 500;
    if (retryable && attempt < retries) {
      const wait = Number(res.headers.get("Retry-After")) || 2 ** attempt;
      await new Promise((r) => setTimeout(r, wait * 1000));
      continue;
    }
    throw new VocaError(res.status, data?.error?.code ?? "HTTP_ERROR", data?.error?.message ?? res.statusText, data?.error?.details);
  }
}

export const addWord = (apiKey: string, item: WordInput) =>
  voca<{ id: string; status: "created" | "updated" | "unchanged" }>(apiKey, "POST", "/external/vocabulary", item);

export async function addWords(apiKey: string, items: (WordInput | string)[], defaults: Partial<WordInput> = {}) {
  const results = [];
  for (let start = 0; start < items.length; start += 100) {
    const body = await voca<{ results: any[] }>(apiKey, "POST", "/external/vocabulary/batch", {
      ...defaults,
      items: items.slice(start, start + 100),
    });
    results.push(...body.results.map((r) => ({ ...r, index: r.index + start })));
  }
  return results;
}

// await addWord(process.env.VOCA_API_KEY!, { word: "leverage", translation: "tận dụng" });
// await addWords(key, ["hedge", "yield"], { source: "my_app", tags: ["Quant"] });
```

---

## Extension trình duyệt (Manifest V3)

Bôi đen một từ trên trang → chuột phải → **Lưu vào Voca**. Câu chứa từ và tiêu đề trang được gửi kèm làm ngữ cảnh.

`manifest.json`:

```json
{
  "manifest_version": 3,
  "name": "Lưu vào Voca",
  "version": "1.0",
  "permissions": ["contextMenus", "storage", "scripting", "notifications"],
  "host_permissions": ["https://voca-zeta-five.vercel.app/*"],
  "background": { "service_worker": "background.js" },
  "options_page": "options.html"
}
```

`options.html`: người dùng dán API key của **chính họ**. Không nhúng một key chung vào extension.

```html
<label>Voca API key <input id="key" size="60"></label>
<button id="save">Lưu</button>
<script src="options.js"></script>
```

`options.js`:

```js
const input = document.getElementById("key");
chrome.storage.sync.get("vocaKey").then(({ vocaKey }) => (input.value = vocaKey || ""));
document.getElementById("save").onclick = () => chrome.storage.sync.set({ vocaKey: input.value.trim() });
```

`background.js`:

```js
const VOCA = "https://voca-zeta-five.vercel.app/api/v1";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "save-to-voca", title: "Lưu \"%s\" vào Voca", contexts: ["selection"] });
});

// Runs inside the page: returns the sentence that contains the selection.
function sentenceAroundSelection() {
  const sel = window.getSelection();
  const text = sel && sel.anchorNode ? sel.anchorNode.textContent || "" : "";
  const word = sel ? sel.toString().trim() : "";
  const at = text.indexOf(word);
  if (!word || at < 0) return null;
  const start = Math.max(text.lastIndexOf(".", at) + 1, 0);
  const endDot = text.indexOf(".", at + word.length);
  return text.slice(start, endDot < 0 ? undefined : endDot + 1).trim().slice(0, 2000);
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const { vocaKey } = await chrome.storage.sync.get("vocaKey");
  if (!vocaKey) return chrome.runtime.openOptionsPage();

  const [{ result: sentence } = {}] = await chrome.scripting
    .executeScript({ target: { tabId: tab.id }, func: sentenceAroundSelection })
    .catch(() => []);

  const res = await fetch(`${VOCA}/external/vocabulary`, {
    method: "POST",
    headers: { "X-API-Key": vocaKey, "Content-Type": "application/json" },
    body: JSON.stringify({
      word: info.selectionText.trim().slice(0, 200),
      source: "chrome_extension",
      context: { sentence, source_title: tab.title, url: tab.url, source_type: "article" },
    }),
  });
  const data = await res.json();
  const message = res.ok
    ? { created: "Đã lưu từ mới", updated: "Đã bổ sung ngữ cảnh", unchanged: "Từ này đã có" }[data.status]
    : data.error?.message ?? "Lỗi";
  chrome.notifications.create({ type: "basic", iconUrl: "icon.png", title: "Voca", message: `${info.selectionText}: ${message}` });
});
```
