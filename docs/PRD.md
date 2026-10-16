# ROOMAX 제품요구사항 정의서 v0.1
작성일: 2026-10-16

## 1. 목표
1동 9개 임대 호실과 별도 주인세대를 관리하는 개인용 웹앱을 먼저 구축하고, 데이터 구조는 다중 건물·다중 사용자 SaaS로 확장 가능하도록 설계한다.

## 2. 현재 운영 전제
- 다가구주택 1동: 임대 원룸 9호실 + 별도 주인세대 1개
- 월세 납부일은 임차인별로 상이; 관리비는 월세 포함; 개별 전기는 임차인 직접 납부
- 임대 입금, 공용 전기·수도·청소비, 개인 생활비가 단일 은행계좌에 혼재
- 계약서 원본은 종이; 사진 촬영 및 OCR 등록 필요
- 개인 단독 명의의 아파트(아들 거주)와 상속 농촌주택은 자산·세무 관리에 포함
- 세무서·지자체 사업자등록 여부, 배우자 주택 보유, 주택별 기준시가 등은 검증 필요

## 3. 핵심 화면
1. 홈: 호실 현황, 월 청구액, 확인 입금, 미납, 예정 지출, 세금 일정, 확인 필요 항목
2. 호실: 임대/자가 유형, 층·호, 면적, 상태, 계약 및 수납 타임라인
3. 계약: 종이계약서 이미지 OCR, 필드 검수, 갱신 이력, 보증금 반환 일정
4. 은행 거래: CSV/XLSX 가져오기, 중복 탐지, 거래분류, 호실 매칭, 수동 승인
5. 운영비: 공용 전기, 수도, 청소, 수리, 주인세대 비용, 개인 생활비 분리
6. 메시지: 호실/층/전체 대상 선택, 템플릿, 발송 승인, 발송 결과와 이력
7. 세무: 자산별 소유 정보, 세금별 주택수 판정, 신고 증빙, 일정, 추정 세액
8. 전월세 분석: 월세·전세 시나리오, 간주임대료 조건, 세후수익, 반환유동성
9. AI 비서: 질의응답, 이상지출, 미납 원인, 월말 결산 요약
10. 설정: 계좌, 발송 채널, OCR, 접근권한, 백업·복구

## 4. 주요 규칙
- 입금 매칭은 계좌 거래 고유키/일자/금액/입금자/기존 별칭을 사용하고, 불확실하면 검토 대기
- 납부일 경과만으로 독촉 금지: 최신 거래내역 확인 + 유예기간 + 관리자 승인
- 보증금 수령은 매출이 아닌 반환의무(부채)로 분리
- 개인비용, 주인세대 비용, 공용운영비를 별도 분류하고 혼합 거래는 비율 배분 지원
- 모든 자동 분류는 근거, 신뢰도, 수정 이력 보관
- 세금 추정은 귀속연도·법령 버전·입력자료 상태를 표시하고 신고 확정으로 표현하지 않음
- 개인정보는 암호화·접근통제·보존기간·삭제·발송 동의/법적 근거 점검 적용

## 5. 데이터 모델 (핵심 테이블)
organizations(id,name), users(id,organization_id,role), properties(id,organization_id,type,address), units(id,property_id,unit_no,use_type), tenants(id,organization_id,name,phone), leases(id,unit_id,tenant_id,start_date,end_date,deposit,rent,due_day,status), lease_documents(id,lease_id,file_path,ocr_json,verified_at), bank_accounts(id,organization_id,alias), transactions(id,bank_account_id,occurred_at,amount,direction,description,fingerprint), transaction_allocations(id,transaction_id,lease_id,category,amount,review_status), charges(id,lease_id,period,due_date,amount,status), payments(id,charge_id,transaction_allocation_id,amount), expenses(id,property_id,unit_id,category,amount,date,document_id), deposits(id,lease_id,amount,received_at,returned_at), assets(id,organization_id,type,ownership_share,assessed_value), tax_cases(id,organization_id,tax_year,tax_type,input_snapshot,result,status), notifications(id,organization_id,tenant_id,channel,template,status,approved_at,sent_at), maintenance_tickets(id,unit_id,description,status), audit_logs(id,user_id,action,entity_type,entity_id,created_at).

## 6. 기술 설계
- 프런트엔드: Next.js + TypeScript + Tailwind CSS, 모바일 반응형 PWA
- 백엔드: FastAPI 또는 Next.js API; PostgreSQL; 객체 스토리지(계약서 이미지)
- 인증: 관리자 MFA, 서버측 권한검사, 향후 tenant_id 기반 테넌트 격리 및 RLS
- OCR: 문서 이미지 업로드 후 추출, 검수 후 반영; AI가 계약 내용을 확정하지 않음
- 은행: 초기 CSV/XLSX; 향후 합법적 금융 API 계약 및 권한 확보 후 연동
- 메시지: 문자/알림톡 사업자 연동, 발송 전 승인 및 발송 기록
- 세무: 규칙엔진(귀속연도별 버전), 국세청 공식 안내 링크, 자료 내보내기; 자동 신고 기능은 연계 검증 후

## 7. 구현 단계
MVP: 자산·호실, 계약 OCR 검수, 월 청구 생성, 은행 거래 가져오기/매칭, 운영비 분리, 대시보드, 백업
2차: 문자·알림톡, 계약만료/미납 알림, 증빙 및 세무 준비, 전월세 시뮬레이션, AI 비서
3차: 임차인 포털, 은행 API, 다중건물·권한, 구독결제, 운영 감사/모니터링

## 8. 테스트 및 완료 기준
- 9개 호실의 서로 다른 납부일에 맞춰 청구 정확 생성
- 동일 금액/다른 입금자, 부분납부, 선납, 연체, 보증금 수령/반환 테스트
- 동일 파일 재업로드 시 거래 중복 없음
- 생활비가 임대 순운영수익에 포함되지 않음
- 데이터 미갱신 상태에서 자동 독촉 발송되지 않음
- 계약 OCR 결과는 관리자 승인 전 원장에 확정되지 않음
- 세무 계산 결과에 입력자료·귀속연도·법령 근거가 표시됨
- 사용자 데이터 내보내기/백업/복구 성공

## 9. 다음 작업
실제 호실 번호, 월세·보증금, 납부일을 입력할 온보딩 화면과 CSV 업로드 샘플을 만들고, 개발용 저장소에서 위 데이터 모델을 마이그레이션한다.
