// Firebase 인증 관련 모듈
import { 
  getAuth, 
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut,
  GoogleAuthProvider,
  signInWithPopup,
  onAuthStateChanged
} from 'firebase/auth';
import { app } from './firebase';

// getAuth로 인증 객체 가져오기
const auth = getAuth(app);

// Google 로그인 제공자 생성
const googleProvider = new GoogleAuthProvider();

// 이메일/비밀번호로 로그인
export const loginWithEmail = async (email, password) => {
  try {
    const userCredential = await signInWithEmailAndPassword(auth, email, password);
    return userCredential.user;
  } catch (error) {
    console.error('로그인 오류:', error);
    throw error;
  }
};

// 이메일/비밀번호로 회원가입
export const registerWithEmail = async (email, password) => {
  try {
    const userCredential = await createUserWithEmailAndPassword(auth, email, password);
    return userCredential.user;
  } catch (error) {
    console.error('회원가입 오류:', error);
    throw error;
  }
};

// Google로 로그인
export const loginWithGoogle = async () => {
  try {
    const result = await signInWithPopup(auth, googleProvider);
    return result.user;
  } catch (error) {
    console.error('Google 로그인 오류:', error);
    throw error;
  }
};

// 로그아웃
export const logout = async () => {
  try {
    await signOut(auth);
    console.log('로그아웃 성공');
    return true;
  } catch (error) {
    console.error('로그아웃 오류:', error);
    throw error;
  }
};

// 사용자 상태 변경 감지
export const onAuthChange = (callback) => {
  return onAuthStateChanged(auth, (user) => {
    if (user) {
      console.log('로그인 사용자:', user.displayName || user.email);
    } else {
      console.log('로그인되지 않음');
    }
    callback(user);
  });
};

// 인증 객체를 전역 객체에 할당
window.firebaseAuthMethods = {
  loginWithEmail,
  registerWithEmail,
  loginWithGoogle,
  logout,
  onAuthChange
}; 