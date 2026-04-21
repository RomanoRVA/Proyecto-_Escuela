

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Base_De_Datos.settings')

application = get_wsgi_application()
