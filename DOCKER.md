# Docker로 한 번에 실행하기

화면 · 서버 · DB를 명령 하나로 켭니다. 내 컴퓨터에 Python · Node · PostgreSQL을 따로 설치하지 않아도 됩니다.

## 처음 한 번

1. [Docker Desktop](https://www.docker.com/products/docker-desktop/)을 설치하고 실행합니다 (고래 아이콘이 초록색이 되면 준비 완료).
2. 저장소 폴더에서 설정 파일을 복사합니다.
   ```powershell
   copy .env.example .env
   ```

## 켜고 끄기

| 하고 싶은 것 | 명령 |
| --- | --- |
| 전부 켜기 | `docker compose up` |
| 화면 없이 서버 + DB만 | `docker compose up db server` |
| 끄기 (데이터는 남음) | `Ctrl+C` 후 `docker compose down` |
| DB를 비우고 처음부터 | `docker compose down -v` |
| 한 곳의 로그만 보기 | `docker compose logs -f server` |

## 켜졌는지 확인

| 무엇 | 주소 | 정상일 때 |
| --- | --- | --- |
| 화면 | http://localhost:3000 | 첫 화면이 뜸 |
| 서버 상태 | http://localhost:8000/api/v1/health | `{"status":"ok"}` |
| 서버 API 문서 | http://localhost:8000/docs | Swagger 화면 |
| DB | localhost:5432 · 아이디/비번 `app`/`app` · DB 이름 `settle` | DB 도구로 접속됨 |

## 코드를 고치면

`web/`, `server/` 폴더가 컨테이너와 연결돼 있어서 **저장하면 바로 반영**됩니다. 다시 켤 필요가 없습니다.
`requirements.txt`나 `package.json`에 라이브러리를 추가했을 때만 `docker compose restart server` (또는 `web`) 하세요.

## 파트별로 알아 둘 것

- **화면 (프론트엔드)**: 컨테이너는 `npm install` 다음 `npm run dev -- --host 0.0.0.0 --port 3000`을 실행합니다 (Vite 기준). 서버 주소는 `VITE_API_BASE_URL`(`http://localhost:8000/api/v1`)로 들어옵니다. 다른 방식으로 틀을 만들면 `docker-compose.yml`의 `web` 줄을 같이 고쳐주세요.
- **서버 (백엔드)**: `server/requirements.txt`를 설치하고 `uvicorn app.main:app --reload`로 켭니다. DB 주소는 `DATABASE_URL`, 사진 저장 폴더는 `RECEIPT_STORAGE_PATH`(`/data/receipts`)로 들어옵니다.
- **OCR (V2)**: RabbitMQ와 Worker는 V2를 시작할 때 이 파일에 추가합니다.
- **LLM (V3)**: `docker compose --profile llm up` 하면 llama.cpp 서버(EXAONE 3.5 2.4B)가 8080 포트로 켜집니다. 처음에는 모델(약 1.5GB)을 받느라 몇 분 걸립니다.

## 안 될 때

| 증상 | 해결 |
| --- | --- |
| `port is already allocated` | 그 포트를 쓰는 프로그램(따로 켠 서버, 로컬 PostgreSQL 등)을 끄고 다시 켜기 |
| `Cannot connect to the Docker daemon` | Docker Desktop이 켜져 있는지 확인 |
| 서버가 `requirements.txt`를 못 찾음 | `server/` 틀이 develop에 병합됐는지 확인 (`git pull origin develop`) |
| 화면이 `package.json`을 못 찾음 | `web/` 틀이 아직 없으면 `docker compose up db server`로 서버 + DB만 켜기 |
