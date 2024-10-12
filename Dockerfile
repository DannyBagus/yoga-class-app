# Dockerfile for Django Applications

# Section 1- Base Image
FROM python:3.8-slim

# Section 2- Python Interpreter Flags
ENV PYTHONUNBUFFERED 1  
ENV PYTHONDONTWRITEBYTECODE 1
ENV LANG de_DE.UTF-8
ENV LC_ALL de_DE.UTF-8

# Section 3- Compiler and OS libraries
RUN apt-get update \  
  && apt-get install -y --no-install-recommends build-essential default-mysql-server default-libmysqlclient-dev locales \  
  && sed -i -e 's/# de_DE.UTF-8 UTF-8/de_DE.UTF-8 UTF-8/' /etc/locale.gen \
  && dpkg-reconfigure --frontend=noninteractive locales \ 
  && rm -rf /var/lib/apt/lists/*

# Section 4- Project libraries and User Creation
COPY requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt \  
    && /usr/local/bin/python -m pip install --upgrade pip \
    && rm -rf /tmp/requirements.txt \  
    && useradd -U app_user \ 
    && install -d -m 0755 -o app_user -g app_user /app/static

# Section 5- Code and User Setup
WORKDIR /app

USER app_user:app_user

COPY --chown=app_user:app_user . .

# Section 6- Docker Run Checks and Configurations 
CMD python manage.py makemigrations \  
    && python manage.py migrate \
    && python manage.py collectstatic --noinput \
    && python manage.py runserver 0.0.0.0:8000