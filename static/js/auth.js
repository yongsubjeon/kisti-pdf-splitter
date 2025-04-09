// FirebaseUI 인스턴스 생성
const ui = new firebaseui.auth.AuthUI(firebase.auth());

// FirebaseUI 구성
const uiConfig = {
  callbacks: {
    signInSuccessWithAuthResult: function(authResult, redirectUrl) {
      // 사용자가 성공적으로 로그인
      const user = authResult.user;
      console.log("로그인 성공:", user.displayName);
      
      // 세션 저장
      sessionStorage.setItem('user', JSON.stringify({
        uid: user.uid,
        email: user.email,
        displayName: user.displayName || '사용자'
      }));
      
      // 메인 페이지로 리디렉션
      window.location.href = '/';
      return false; // 자동 리디렉션 방지
    },
    uiShown: function() {
      // 로딩 표시기 숨기기
      document.getElementById('loader').style.display = 'none';
    }
  },
  // 로그인 플로우 방식 (redirect 또는 popup)
  signInFlow: 'redirect',
  // 제공할 로그인 방법
  signInOptions: [
    // 이메일/비밀번호 로그인
    firebase.auth.EmailAuthProvider.PROVIDER_ID,
    // 구글 로그인
    firebase.auth.GoogleAuthProvider.PROVIDER_ID
  ],
  // 이용약관 URL (실제 URL로 변경 필요)
  tosUrl: '/terms',
  // 개인정보처리방침 URL (실제 URL로 변경 필요)
  privacyPolicyUrl: '/privacy'
};

// 현재 페이지가 로그인 페이지인지 확인
if (window.location.pathname === '/login') {
  // FirebaseUI 시작
  ui.start('#firebaseui-auth-container', uiConfig);
}

// 사용자 로그인 상태 모니터링
firebase.auth().onAuthStateChanged(function(user) {
  const loginStatus = document.getElementById('login-status');
  const logoutButton = document.getElementById('logout-button');
  
  if (user) {
    // 사용자가 로그인한 상태
    console.log("로그인 사용자:", user.displayName || user.email);
    
    // 로그인 상태 UI 표시
    if (loginStatus) {
      loginStatus.textContent = `${user.displayName || user.email}님 환영합니다`;
    }
    
    // 로그아웃 버튼 표시
    if (logoutButton) {
      logoutButton.style.display = 'block';
    }
  } else {
    // 사용자가 로그아웃한 상태
    console.log("로그인되지 않음 - 앱 접근 허용");
    
    // 로그아웃 상태 UI 표시
    if (loginStatus) {
      loginStatus.textContent = '로그인되지 않음';
    }
    
    // 로그아웃 버튼 숨기기
    if (logoutButton) {
      logoutButton.style.display = 'none';
    }
    
    // Firebase 로그인에서 넘어온 경우 자동 리디렉션 제거
    // 로그인 여부에 관계없이 앱에 접근 허용
    /*
    // 기존 리디렉션 코드 주석 처리
    if (window.location.pathname !== '/login') {
      // 일부 공개 페이지는 제외
      const publicPages = ['/login', '/terms', '/privacy'];
      if (!publicPages.includes(window.location.pathname)) {
        window.location.href = '/login';
      }
    }
    */
  }
});

// 로그아웃 버튼 이벤트 리스너
document.addEventListener('DOMContentLoaded', function() {
  const logoutButton = document.getElementById('logout-button');
  if (logoutButton) {
    logoutButton.addEventListener('click', function() {
      firebase.auth().signOut().then(function() {
        // 로그아웃 성공
        console.log("로그아웃 성공");
        sessionStorage.removeItem('user');
        window.location.href = '/login';
      }).catch(function(error) {
        // 로그아웃 실패
        console.error("로그아웃 실패:", error);
      });
    });
  }
}); 