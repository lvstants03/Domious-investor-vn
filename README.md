# Dominus Investor (VNStock & TCBS Trading Engine)

Hệ thống phân tích định lượng, backtest, quản lý danh mục và giao dịch chứng khoán tự động kết nối trực tiếp với API của Công ty Cổ phần Chứng khoán Kỹ thương (TCBS).

## Tính năng chính

- **Quản lý tài sản đa tiểu khoản**: Tự động đồng bộ số dư tiền mặt (PPSE), danh mục cổ phiếu nắm giữ và các khoản vay margin cho cả tài khoản thường (Normal), ký quỹ (Margin) và phái sinh (Derivative).
- **Quản trị rủi ro Margin (Realtime)**: Theo dõi sát sao tỷ lệ an toàn tài khoản (Rtt), tổng dư nợ margin thực tế và cảnh báo ngưỡng gọi ký quỹ.
- **Dòng tiền thông minh (BSA)**: Tích hợp phân tích dòng tiền Shark/Wolf và giao dịch thỏa thuận lô lớn đột biến thời gian thực.
- **Đặt lệnh tự động (Trading Bot)**: Hỗ trợ đặt/sửa/hủy lệnh cổ phiếu và phái sinh tự động thông qua API của TCInvest.

## Cài đặt nhanh

### Yêu cầu hệ thống
- Python 3.10+
- PostgreSQL & Redis (chạy Docker hoặc local)

### Các bước cài đặt

1. **Tạo môi trường ảo và cài đặt thư viện**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Trên Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Cấu hình biến môi trường**:
   Sao chép tệp `.env.example` thành `.env` và điền đầy đủ các thông tin API Key TCBS cũng như cấu hình kết nối CSDL:
   ```bash
   cp .env.example .env
   ```

3. **Khởi chạy API Server**:
   ```bash
   uvicorn src.main:app --host 0.0.0.0 --port 8002 --reload
   ```

## Cấu hình Biến Môi Trường (`.env`)

| Biến | Mô tả | Giá trị ví dụ |
| :--- | :--- | :--- |
| `TCBS_API_KEY` | Khóa API Open API của TCBS cấp | `10000319258-xxxx-xxxx...` |
| `TCBS_BASE_URL` | Endpoint Open API TCBS | `https://openapi.tcbs.com.vn` |
| `DATABASE_URL` | Đường dẫn kết nối CSDL PostgreSQL | `postgresql+asyncpg://postgres:123@localhost:5432/markovlotteai` |
| `REDIS_HOST` | Host của Redis cache | `127.0.0.1` |
| `REDIS_PORT` | Port của Redis cache | `6379` |

## Giấy phép

Dự án này được phát hành dưới giấy phép [MIT License](LICENSE).
