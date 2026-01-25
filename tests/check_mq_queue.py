
import pika
import os

def check_queues():
    url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    params = pika.URLParameters(url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    
    queues = ['buy-signals', 'sell-orders']
    
    print("=== RabbitMQ Queue Status ===")
    for q in queues:
        try:
            # Passive declaration generates an exception if queue doesn't exist.
            # But queue_declare with passive=True returns method frame with message_count
            res = channel.queue_declare(queue=q, passive=True)
            print(f"Queue '{q}': {res.method.message_count} messages, {res.method.consumer_count} consumers")
        except Exception as e:
            print(f"Queue '{q}': Not found or error: {e}")
            # Re-open channel if it closed due to exception
            if channel.is_closed:
                channel = connection.channel()
                
    connection.close()

if __name__ == "__main__":
    check_queues()
