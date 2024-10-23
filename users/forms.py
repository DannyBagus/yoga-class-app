from typing import Any
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordResetForm, SetPasswordForm

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        
        self.fields['username'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-[90%]"
        self.fields['email'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-[90%]"
        self.fields['first_name'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-[90%]"
        self.fields['last_name'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-[90%]"
        self.fields['password1'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-[90%]"
        self.fields['password2'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-[90%]"

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2')

class CustomAuthenticateForm(AuthenticationForm):
    
    def __init__(self, request: Any = ..., *args: Any, **kwargs: Any) -> None:
        super().__init__(request, *args, **kwargs)
        
        self.fields['username'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-[90%]"
        self.fields['password'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-[90%]"
        
class CustomPasswordResetForm(PasswordResetForm):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({
            'class': 'text-black rounded-xl m-4 p-4 w-[90%]',
            'placeholder': 'Deine E-Mail Adresse',
        })
        
class CustomSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].widget.attrs.update({
            'class': 'text-black rounded-xl m-4 p-4 w-[90%]',
        })
        self.fields['new_password2'].widget.attrs.update({
            'class': 'text-black rounded-xl m-4 p-4 w-[90%]',
        })