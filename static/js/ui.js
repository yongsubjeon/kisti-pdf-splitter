// UI 관련 스크립트
document.addEventListener('DOMContentLoaded', function() {
  console.log('UI 스크립트 로드됨');
  
  // Firebase 인증 객체 가져오기
  const auth = firebase.auth();
  
  if (!auth) {
    console.error('Firebase 인증 객체를 찾을 수 없습니다.');
    return;
  }
  
  // 사용자 로그인 상태 모니터링
  auth.onAuthStateChanged(function(user) {
    console.log('인증 상태 변경:', user ? '로그인' : '로그아웃');
    
    const loginStatus = document.getElementById('login-status');
    const logoutButton = document.getElementById('logout-button');
    
    if (user) {
      // 사용자가 로그인한 상태
      if (loginStatus) {
        loginStatus.textContent = `${user.displayName || user.email}님 환영합니다`;
      }
      if (logoutButton) {
        logoutButton.style.display = 'block';
      }
      
      // 이미 로그인한 상태에서 로그인 페이지로 접근하면 메인 페이지로 리디렉션
      if (window.location.pathname === '/login' || window.location.pathname === '/register') {
        console.log('이미 로그인한 상태로 메인 페이지로 리디렉션');
        window.location.href = '/';
      }
    } else {
      // 사용자가 로그아웃한 상태
      if (loginStatus) {
        loginStatus.textContent = '로그인되지 않음';
      }
      if (logoutButton) {
        logoutButton.style.display = 'none';
      }
      
      // 로그인 필요한 페이지에서 로그인 페이지로 리디렉션
      const publicPages = ['/login', '/register', '/terms', '/privacy'];
      const path = window.location.pathname;
      
      if (!publicPages.includes(path)) {
        console.log('로그인이 필요한 페이지에서 로그인 페이지로 리디렉션:', path);
        window.location.href = '/login';
      }
    }
  });

  // 로그아웃 버튼 이벤트 핸들러
  const logoutButton = document.getElementById('logout-button');
  if (logoutButton) {
    logoutButton.addEventListener('click', function() {
      auth.signOut().then(function() {
        // 로그아웃 성공
        console.log('로그아웃 성공');
        sessionStorage.removeItem('user');
        window.location.href = '/login';
      }).catch(function(error) {
        // 로그아웃 실패
        console.error('로그아웃 실패:', error);
      });
    });
  }
}); 