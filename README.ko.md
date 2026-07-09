<!-- ARTEMIS-IGNIS-TOP:START -->
<p align="center">
  <img src="docs/assets/artemis-ignis-emblem-top.jpg" alt="Artemis-Ignis 엠블럼" width="360" />
</p>
<!-- ARTEMIS-IGNIS-TOP:END -->

<h1 align="center">Agent Orchestration Platform</h1>

<p align="center"><a href="README.md">English README</a></p>

엔터프라이즈 환경에서 자율 AI 에이전트를 오케스트레이션하기 위한 분산 플랫폼입니다. 에이전트 생명주기 관리, 에이전트 간 통신, 작업 스케줄링, 검증 가능한 실행을 제공합니다.

## 주요 기능

- **에이전트 생명주기 관리** — 에이전트 등록, 배포, 확장, 종료
- **지능형 작업 스케줄링** — 리소스 상황을 고려한 우선순위 기반 스케줄링
- **에이전트 간 통신** — 증명(attestation) 기반의 안전한 메시지 전달
- **엔터프라이즈 보안** — RBAC, 감사 로깅, 시크릿 관리
- **관측 가능성** — 분산 트레이싱, 메트릭, 구조화된 로깅
- **플러그인 아키텍처** — 커스텀 플러그인과 미들웨어로 확장 가능

## 빠른 시작

```bash
# 저장소 클론 및 의존성 설치 (uv 필요)
git clone https://github.com/Artemis-ignis/AgentOrchestration.git
cd AgentOrchestration
make install

# 테스트 실행
make test

# API 서버 실행 (http://localhost:8000)
make run
```

자세한 내용은 [영어 README](README.md)를 참고하세요.

## 기여

기여 방법은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.

## 보안

취약점은 [보안 정책](SECURITY.md)에 따라 제보해 주세요.
