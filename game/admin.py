from django.contrib import admin

from .models import Class, GraphemeSound, Kid, SoundMiss, Word, WordSound


@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "teacher", "class_goal", "created")
    search_fields = ("name", "code", "teacher__username")
    list_filter = ("teacher",)


admin.site.register(Kid)
admin.site.register(Word)
admin.site.register(SoundMiss)
admin.site.register(GraphemeSound)
admin.site.register(WordSound)
