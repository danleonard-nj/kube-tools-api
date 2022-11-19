FROM azureks.azurecr.io/base/pybase:v2 as base

WORKDIR /app

RUN mkdir utilities
RUN apt-get update -y
# RUN apt-get update && apt-get dist-upgrade -y

RUN apt-get install -y wget
RUN wget https://fastdl.mongodb.org/tools/db/mongodb-database-tools-ubuntu1804-x86_64-100.6.0.tgz
RUN mkdir /app/utilities/mongotools 
RUN tar -xf mongodb-database-tools-ubuntu1804-x86_64-100.6.0.tgz -C /app/utilities/mongotools --strip-components 1


COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
RUN pip install ddtrace

FROM base AS main

COPY . .
EXPOSE 80

CMD ["bash", "startup.sh"]
