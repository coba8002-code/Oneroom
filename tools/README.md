# tools — 앱 밖에서 쓰는 보조 도구

앱(backend·frontend)에 들어가지 않는 일회성·개발용 도구입니다. **실제 장부 자료(통장 내역·계약서·엑셀)는 이 공개 저장소에 두지 않습니다** — 비공개 저장소 `oneroom-ledger` 에 둡니다.

## bank/ — 은행 내역 변환

| 파일 | 하는 일 |
|---|---|
| `woori_decrypt.mjs` | 우리은행 보안메일(암호 HTML) 거래내역을 오프라인 브라우저로 열어 글자로 풉니다 |
| `woori_to_csv.py` | 풀린 글자(탭 구분)에서 거래 줄만 모아 앱이 읽는 CSV(거래일시·적요·기재내용·출금·입금·잔액·취급점)로 만듭니다 |

```bash
(cd e2e && npm ci)                                   # playwright
node tools/bank/woori_decrypt.mjs mail/ dec/ '<메일 비밀번호>'
python tools/bank/woori_to_csv.py woori.csv dec/*.txt
```

인터넷뱅킹에서 받은 `.xls`·`.xlsx`·`.csv` 는 변환 없이 앱의 '통장 내역 가져오기'에 바로 올리면 됩니다 (`backend/app/services/bank_import.py`).

## dev/ — 로컬 시험용 가짜 서버

| 파일 | 흉내 내는 것 | 실행 |
|---|---|---|
| `fake_anthropic.py` | Claude Messages API (AI 비서 도구 호출 흐름) | `uvicorn tools.dev.fake_anthropic:app --port 9200` |
| `fake_supabase.py` | Supabase Storage REST (업로드·백업 저장, 서명 URL) | `uvicorn tools.dev.fake_supabase:app --port 9100` |

Vercel 처럼 띄워 보려면 백엔드를 `ROOMAX_STORAGE=supabase`, `ROOMAX_SUPABASE_URL=http://127.0.0.1:9100`, `ROOMAX_SUPABASE_SERVICE_KEY=fake-service-key` 로 실행합니다. 가짜 서버의 키는 시험용 고정값이며 실제 비밀값을 넣지 마십시오.
