// Firebase 구성
const firebaseConfig = {
  apiKey: "AIzaSyD-UpDOnKQN8n5kXrinjNyHQu7YiNUNt0g",
  authDomain: "kisti-acd6a.firebaseapp.com",
  projectId: "kisti-acd6a",
  storageBucket: "kisti-acd6a.firebasestorage.app",
  messagingSenderId: "28189232402",
  appId: "1:28189232402:web:9b302401f88d93a0c7f7cb",
  measurementId: "G-058J5VQ85Y"
};

// Firebase 초기화
// 브라우저에서는 window.firebase 객체를 사용하고,
// Node.js 환경에서는 require로 불러온 firebase를 사용합니다.
if (typeof firebase === 'undefined' && typeof require !== 'undefined') {
  // Node.js 환경에서 실행 중일 때
  const firebase = require('firebase/app');
  require('firebase/auth');
  require('firebase/analytics');
}

// Firebase 앱 초기화
if (firebase.apps.length === 0) {
  firebase.initializeApp(firebaseConfig);
  
  // Analytics 초기화 시도
  try {
    if (firebase.analytics) {
      firebase.analytics();
    }
  } catch (e) {
    console.log('Analytics 초기화 오류:', e);
  }
}

// 콘솔에 초기화 성공 메시지 출력
console.log("Firebase가 초기화되었습니다."); 