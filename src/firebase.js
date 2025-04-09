// Firebase 앱 초기화를 위한 모듈
import { initializeApp } from 'firebase/app';
import { getAuth } from 'firebase/auth';
import { getAnalytics } from 'firebase/analytics';

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

// Firebase 앱 초기화
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

// Analytics 초기화 (브라우저 환경에서만)
let analytics = null;
if (typeof window !== 'undefined') {
  try {
    analytics = getAnalytics(app);
  } catch (e) {
    console.log('Analytics를 초기화하는 중 오류 발생:', e);
  }
}

// 전역 객체에 할당
window.firebaseApp = app;
window.firebaseAuth = auth;

console.log("Firebase가 초기화되었습니다.");

export { app, auth, analytics }; 