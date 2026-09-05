from django.contrib import admin

from .models import Config, GraphemeSound, Kid, SoundMiss, Word, WordSound

admin.site.register(Kid)
admin.site.register(Word)
admin.site.register(SoundMiss)
admin.site.register(Config)
admin.site.register(GraphemeSound)
admin.site.register(WordSound)
