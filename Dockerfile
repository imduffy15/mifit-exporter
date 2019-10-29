FROM python:3.6-slim-buster

ENV PIP_NO_CACHE_DIR "true"

WORKDIR /

RUN pip install --upgrade pip

COPY Pipfile.lock /
COPY pipenv-install.py /

RUN /pipenv-install.py && \
    rm -fr /usr/local/lib/python3.6/site-packages/pip && \
    rm -fr /usr/local/lib/python3.6/site-packages/setuptools

FROM python:3.6-slim-buster

ARG VERSION=dev

COPY --from=0 /usr/local/lib/python3.6/site-packages /usr/local/lib/python3.6/site-packages
COPY gpx_exporter /gpx_exporter

RUN sed -i "s/^__version__ = .*/__version__ = \"${VERSION}\"/" /gpx_exporter/__init__.py

ENTRYPOINT ["python", "-m", "gpx_exporter"]
