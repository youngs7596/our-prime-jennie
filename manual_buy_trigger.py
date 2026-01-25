import pika
import json
import datetime

def trigger():
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()
    queue_name = 'buy-signals'
    
    message = {
        'stock_code': '005930',
        'stock_name': 'Samsung Elec',
        'signal_type': 'MANUAL_TEST',
        'signal_reason': 'Manual Trigger via Python Script',
        'current_price': 70000,
        'llm_score': 95,
        'market_regime': 'BULL',
        'timestamp': datetime.datetime.now().isoformat()
    }
    
    channel.basic_publish(exchange='', routing_key=queue_name, body=json.dumps(message))
    print(f" [x] Sent {message}")
    connection.close()

if __name__ == '__main__':
    trigger()
