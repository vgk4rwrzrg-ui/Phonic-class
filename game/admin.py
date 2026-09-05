from django.contrib import admin

from .models import Config, Kid, SoundMiss, Word

admin.site.register(Kid)
admin.site.register(Word)
admin.site.register(SoundMiss)
admin.site.register(Config)
