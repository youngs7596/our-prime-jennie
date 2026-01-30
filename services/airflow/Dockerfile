FROM apache/airflow:2.10.4-python3.11
USER root
# Install system dependencies if needed (e.g. for mysqlclient)
# RUN apt-get update && apt-get install -y default-libmysqlclient-dev pkg-config

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# [Layer Caching] Install project dependencies
COPY services/airflow/requirements.txt /requirements.txt
RUN --mount=type=cache,target=/home/airflow/.cache/pip \
    pip install -r /requirements.txt && \
    pip install pymysql
