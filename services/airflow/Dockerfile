FROM apache/airflow:2.10.4-python3.11
USER root
# Install system dependencies if needed (e.g. for mysqlclient)
# RUN apt-get update && apt-get install -y default-libmysqlclient-dev pkg-config

USER airflow
# Install PyMySQL driver for MariaDB support
RUN pip install --no-cache-dir pymysql
