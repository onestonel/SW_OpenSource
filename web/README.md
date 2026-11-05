# web — 화면 (프론트엔드)

- 프레임워크: React
- 실행 주소: http://localhost:3000
- 서버 API 주소: http://localhost:8000/api/v1

이 폴더는 프론트엔드 담당만 고쳐주세요.

## 실행 방법

### Docker로 (팀 공통)

저장소 맨 위 폴더에서:

```bash
docker compose up
```

→ http://localhost:3000 (화면) · 서버 주소는 `VITE_API_BASE_URL`로 들어옵니다.
라이브러리를 추가했을 때만 `docker compose restart web`.

### Docker 없이

Node.js 22 이상이 필요합니다.

```bash
cd web
npm install
npm run dev
```

→ http://localhost:3000 · 서버는 http://localhost:8000/api/v1 로 연결합니다 (바꾸려면 `VITE_API_BASE_URL`).

### 검사 (web-test와 같음)

```bash
npm run lint    # 코드 검사 (oxlint)
npm run build   # 빌드가 되는지
```
