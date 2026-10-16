import LegalDoc from "@/components/LegalDoc";

export const metadata = { title: "개인정보 처리방침 · ROOMAX" };

export default function Privacy() {
  return (
    <LegalDoc title="개인정보 처리방침 (초안)">
      <section><h2>1. 처리하는 개인정보와 목적</h2>
        <table><thead><tr><th>구분</th><th>항목</th><th>목적</th></tr></thead><tbody>
          <tr><td>회원(필수)</td><td>이름, 이메일, 비밀번호(복원할 수 없는 해시로만 저장), 사업장 이름</td><td>회원 식별, 로그인, 고지</td></tr>
          <tr><td>회원(선택)</td><td>광고성 정보 수신 동의 여부와 일시</td><td>새 기능·할인 안내 (동의한 경우만)</td></tr>
          <tr><td>자동 생성</td><td>로그인 기록, 접속 기기 정보(브라우저 종류)</td><td>보안, 부정 이용 방지</td></tr>
          <tr><td>회원이 입력(위탁)</td><td>임차인 이름·연락처, 계약 내용, 계약서 이미지, 은행 거래내역</td><td>회원의 임대 관리 (회원의 처리를 위탁받아 처리)</td></tr>
        </tbody></table></section>
      <section><h2>2. 보관 기간과 파기</h2>
        <ul><li>탈퇴하면 지체 없이 파기합니다. 다만 법령이 보존을 요구하는 기록은 그 기간 동안 분리 보관합니다
          (예: 유료 서비스의 계약·결제 기록 — 전자상거래법).</li>
          <li>전자적 파일은 복구할 수 없는 방법으로 지웁니다.</li></ul></section>
      <section><h2>3. 처리 위탁</h2>
        <table><thead><tr><th>수탁자</th><th>위탁 업무</th></tr></thead><tbody>
          <tr><td>네이버클라우드㈜ (CLOVA OCR)</td><td>계약서 이미지의 글자 인식 (회원이 계약서를 올리고 OCR이 켜져 있을 때)</td></tr>
          <tr><td>(호스팅 사업자 — 확정 후 기재)</td><td>서버·데이터베이스 운영</td></tr>
          <tr><td>(메일 발송 업체 — 확정 후 기재)</td><td>이메일 주소 확인·비밀번호 재설정 메일 발송</td></tr>
        </tbody></table>
        <p className="mt-2 text-sm text-slate-500">국외 이전: 없음 (수탁자 처리 지역 확인 후 확정).</p></section>
      <section><h2>4. 안전성 확보 조치</h2>
        <ul><li>비밀번호는 scrypt 해시로만 저장, 임차인 연락처·계약서 파일·2단계 인증 키는 암호화 저장</li>
          <li>로그인 세션은 서버에서 폐기 가능, 반복된 로그인 실패 시 일시 차단</li>
          <li>사업장 간 데이터 접근 차단, 역할별 권한(대표·관리자·조회), 변경 기록 보관</li></ul></section>
      <section><h2>5. 정보주체의 권리</h2>
        <p>회원은 자신의 개인정보 열람·정정·삭제·처리정지를 요구할 수 있고, 광고성 정보 수신 동의는 언제든 철회할 수 있습니다.
          임차인 정보에 대한 요구는 해당 임대인(회원)에게 하시면 되며, 서비스는 회원의 처리를 돕습니다.</p></section>
      <section><h2>6. 개인정보 보호책임자</h2>
        <p>(성명·연락처 — 정식 서비스 전 기재)</p></section>
    </LegalDoc>
  );
}
