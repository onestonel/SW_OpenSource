# 같이정산

항목마다 참여자가 다른 공동 지출을 영수증으로 나눠 정산하는 웹 앱입니다.

## 폴더 구조

```
SW_OpenSource/
├── web/        화면 (React, 포트 3000) — 프론트엔드 담당만 수정
├── server/     서버 (Python FastAPI, 포트 8000) — 백엔드 담당만 수정
└── README.md   협업 규칙 — PM이 관리
```

## Git 사용법

### 브랜치

```
main      발표용 안정 버전
  ↑
develop   통합 브랜치 (PR은 여기로)
  ↑
feature/{이슈번호}-{기능명}   예: feature/12-settlement-engine
```

### 작업 순서

1. **Issue 만들기**: GitHub → Issues → New issue → "기능" 템플릿을 고르고, 번호를 확인합니다 (예: #12).
2. **브랜치 만들기**
   ```bash
   git switch develop
   git pull origin develop
   git switch -c feature/12-settlement-engine
   ```
3. **커밋 · 푸시**
   ```bash
   git add .
   git commit -m "feat: 정산 계산 추가 #12"
   git push -u origin feature/12-settlement-engine
   ```
4. **PR 열기**: GitHub에 뜨는 "Compare & pull request" 버튼을 누르고, base를 `develop`으로 맞춘 뒤 템플릿을 채웁니다.
5. **리뷰 · 병합**: 다른 팀원 1명 이상이 승인하고 자동 테스트가 통과하면 "Merge pull request"를 누릅니다.

### 커밋 메시지

| 앞머리 | 언제 |
| --- | --- |
| `feat:` | 새 기능 |
| `fix:` | 버그 수정 |
| `test:` | 테스트 추가 · 수정 |
| `docs:` | 문서 |
| `refactor:` | 동작은 그대로, 코드 정리 |
| `chore:` | 설정 · 폴더 · 빌드 |

끝에 Issue 번호를 붙여주세요. 예: `feat: 영수증 입력 API 추가 #12`

### 병합 조건

- 다른 팀원 1명 이상 승인
- 자동 테스트 통과
- API가 바뀌는 PR은 프론트엔드 담당도 리뷰
