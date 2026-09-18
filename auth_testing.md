# TitanGym authentication testing

Admin login uses `admin@titangym.in` / `Titan@123` and sets an httpOnly access cookie.
Member OTP testing uses `+91 98111 22031` and the development OTP `123456`.

Endpoints:
- POST `/api/auth/login`
- GET `/api/auth/me`
- POST `/api/auth/member/request-otp`
- POST `/api/auth/member/verify-otp`