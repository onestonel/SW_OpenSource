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
main                     발표용 완성본 (태그: v1.0, v1.0.1 …)
  ↑            ↑
release/v1     hotfix/{이슈번호}-{내용}
  ↑
develop                  통합 브랜치 (평소 PR은 여기로)
  ↑
feature/{이슈번호}-{기능명}   예: feature/12-settlement-engine
```

| 브랜치 | 어디서 만드나 | 어디로 병합하나 | 언제 |
| --- | --- | --- | --- |
| `feature/…` | develop | develop | 평소 기능 작업 |
| `release/v1` | develop | main + develop | 시연 직전 마지막 점검 |
| `hotfix/…` | main | main + develop | main에서 급한 버그가 나왔을 때 |

`main`과 `develop`에는 직접 push할 수 없습니다. 모두 PR로 병합하고, 다른 팀원 1명의 승인이 필요합니다.

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

### 시연 전: release

```bash
git switch develop
git pull origin develop
git switch -c release/v1
git push -u origin release/v1
```

1. `release/v1`에서는 새 기능을 넣지 않고, 시연 점검 중 찾은 작은 수정만 합니다.
2. 점검이 끝나면 `release/v1 → main` PR을 열어 병합하고, main에 `v1.0` 태그를 붙입니다.
   ```bash
   git switch main
   git pull origin main
   git tag v1.0
   git push origin v1.0
   ```
3. 점검 중 고친 내용이 빠지지 않게 `release/v1 → develop` PR도 열어 병합합니다.

### 급한 버그: hotfix

main(시연 · 발표 버전)에서 버그가 나왔을 때만 씁니다. 먼저 "버그" 양식으로 Issue를 만듭니다.

```bash
git switch main
git pull origin main
git switch -c hotfix/21-transfer-rounding
# 고치고 커밋
git commit -m "fix: 송금 목록 반올림 오류 수정 #21"
git push -u origin hotfix/21-transfer-rounding
```

1. `hotfix/… → main` PR을 열어 병합하고, `v1.0.1`처럼 끝자리를 올린 태그를 붙입니다.
2. 같은 수정이 develop에도 들어가게 `hotfix/… → develop` PR도 열어 병합합니다.
