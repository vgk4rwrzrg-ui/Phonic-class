from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class TeacherSignupForm(UserCreationForm):
    email = forms.EmailField(
        required=False,
        label="Email (optional)",
        help_text="Only used if you forget your password.",
    )
    class_name = forms.CharField(
        max_length=60,
        label="Your first class name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Room 12"}),
        help_text="You can add more classes later from the dashboard.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
        help_texts = {"username": "Letters, digits and @/./+/-/_ only."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # keep the form compact — trim long built-in help text
        self.fields["password1"].help_text = ""