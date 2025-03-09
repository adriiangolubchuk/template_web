bind = "0.0.0.0:10000"
workers = 2
threads = 4
worker_class = "gthread"
timeout = 120
wsgi_app = "app:create_app()" 