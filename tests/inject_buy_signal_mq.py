
import pika
import json
import datetime

QUEUE_NAME = 'buy-signals'

def inject_mq_signal():
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    
    signal = {
        'candidates': [
            {
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'signal_type': 'TEST_MANUAL_INJECTION',
                'signal_reason': 'E2E Validation Test',
                'current_price': 70000,
                'min_price': 69000, 
                'llm_score': 90,
                'market_regime': 'BULL',
                'source': 'test_script',
                'timestamp': datetime.datetime.now().isoformat(),
                'trade_tier': 'TIER1'
            }
        ]
    }
    
    channel.basic_publish(
        exchange='',
        routing_key=QUEUE_NAME,
        body=json.dumps(signal),
        properties=pika.BasicProperties(
            delivery_mode=2,  # make message persistent
        ))
    
    print(f" [x] Sent 'Test Signal' to {QUEUE_NAME}: {json.dumps(signal)}")
    connection.close()

if __name__ == "__main__":
    inject_mq_signal()
