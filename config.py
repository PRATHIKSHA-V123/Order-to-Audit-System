import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SECRET_KEY = "change-this-later"
DATABASE = os.path.join(BASE_DIR, "database", "factory.db")

STATE_CODE = "33"          # Tamil Nadu
GST_RATE = 5               # percent, as given in the assignment