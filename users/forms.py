from typing import Any
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        
        self.fields['username'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-full"
        self.fields['email'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-full"
        self.fields['first_name'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-full"
        self.fields['last_name'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-full"
        self.fields['password1'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-full"
        self.fields['password2'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-full"

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2')

class CustomAuthenticateForm(AuthenticationForm):
    
    def __init__(self, request: Any = ..., *args: Any, **kwargs: Any) -> None:
        super().__init__(request, *args, **kwargs)
        
        self.fields['username'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-full"
        self.fields['password'].widget.attrs['class'] = "text-black rounded-xl m-4 p-4 w-full"
        
        