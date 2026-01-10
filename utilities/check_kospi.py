
import sys
import os
from datetime import datetime
from dotenv import load_dotenv

# 프로젝트 루트를 경로에 추가
sys.path.append(os.getcwd())

load_dotenv()  # .env 파일 로드

from shared import database

def check_kospi():
    conn = database.get_db_connection()
    if not conn:
        print("❌ DB 연결 실패")
        return

    try:
        cursor = conn.cursor()
        
        # 0001 (KOSPI) 조회
        query = """
            SELECT PRICE_DATE, CLOSE_PRICE 
            FROM STOCK_DAILY_PRICES_3Y 
            WHERE STOCK_CODE = '0001' 
              AND PRICE_DATE >= '2025-07-01'
            ORDER BY PRICE_DATE ASC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print("❌ KOSPI(0001) 데이터가 없습니다.")
            return

        # 데이터 파싱
        data = []
        for row in rows:
            if isinstance(row, dict):
                date = row['PRICE_DATE']
                price = row['CLOSE_PRICE']
            else:
                date = row[0]
                price = row[1]
            data.append((date, float(price)))

        if not data:
            print("❌ 데이터 파싱 실패")
            return

        start_date, start_price = data[0]
        end_date, end_price = data[-1]
        
        returns = (end_price - start_price) / start_price * 100
        
        print("\n📊 KOSPI 지수 변동 현황 (DB 기준)")
        print(f"========================================")
        print(f"시작일: {start_date} | 지수: {start_price:,.2f}")
        print(f"종료일: {end_date} | 지수: {end_price:,.2f}")
        print(f"----------------------------------------")
        print(f"변동률: {returns:+.2f}%")
        print(f"========================================\n")
        
        # 월별 데이터 출력
        print("📅 월별 지수 흐름:")
        current_month = None
        for date, price in data:
            # datetime 객체인지 문자열인지 확인 후 처리
            if isinstance(date, str):
                d = datetime.strptime(date, "%Y-%m-%d")
            else:
                d = date
                
            month = d.strftime("%Y-%m")
            if month != current_month:
                print(f" - {d.strftime('%Y-%m-%d')}: {price:,.2f}")
                current_month = month
        
        # 마지막 날짜 출력
        last_d = data[-1][0]
        if isinstance(last_d, str):
            last_d = datetime.strptime(last_d, "%Y-%m-%d")
        
        if last_d.strftime("%Y-%m") == current_month:
             print(f" - {last_d.strftime('%Y-%m-%d')}: {data[-1][1]:,.2f} (End)")

    except Exception as e:
        print(f"❌ 에러 발생: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_kospi()
