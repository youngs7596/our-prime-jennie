
import pika
import json
import datetime

QUEUE_NAME = 'sell-orders'

def inject_mq_signal():
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    
    signal = {
        'stock_code': '005930',
        'stock_name': '삼성전자',
        'quantity': 10,
        'sell_reason': 'MANUAL_TEST_SELL',
        'current_price': 75000,
        'profit_pct': 25.0,  # Bought @ 60000 -> 75000 is +25%
        'timestamp': datetime.datetime.now().isoformat()
    }
    
    channel.basic_publish(
        exchange='',
        routing_key=QUEUE_NAME,
        body=json.dumps(signal),
        properties=pika.BasicProperties(
            delivery_mode=2,  # make message persistent
        ))
    
    print(f" [x] Sent 'Sell Signal' to {QUEUE_NAME}: {json.dumps(signal)}")
    connection.close()

if __name__ == "__main__":
    inject_mq_signal()
