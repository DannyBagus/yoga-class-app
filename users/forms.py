from typing import Any
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordResetForm, SetPasswordForm

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        
        input_class = "w-full rounded-lg p-3 mb-2 text-black bg-white border border-gray-300 focus:ring-2 focus:ring-[#e46aeb] focus:border-transparent focus:outline-none"
        for field_name in ('username', 'email', 'first_name', 'last_name', 'password1', 'password2'):
            self.fields[field_name].widget.attrs['class'] = input_class

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2')

class CustomAuthenticateForm(AuthenticationForm):
    
    def __init__(self, request: Any = ..., *args: Any, **kwargs: Any) -> None:
        super().__init__(request, *args, **kwargs)
        
        input_class = "w-full rounded-lg p-3 mb-2 text-black bg-white border border-gray-300 focus:ring-2 focus:ring-[#e46aeb] focus:border-transparent focus:outline-none"
        self.fields['username'].widget.attrs['class'] = input_class
        self.fields['password'].widget.attrs['class'] = input_class
        
class CustomPasswordResetForm(PasswordResetForm):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({
            'class': 'w-full rounded-lg p-3 mb-2 text-black bg-white border border-gray-300 focus:ring-2 focus:ring-[#e46aeb] focus:border-transparent focus:outline-none',
            'placeholder': 'Deine E-Mail Adresse',
        })
        
class CustomSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        input_class = "w-full rounded-lg p-3 mb-2 text-black bg-white border border-gray-300 focus:ring-2 focus:ring-[#e46aeb] focus:border-transparent focus:outline-none"
        self.fields['new_password1'].widget.attrs.update({'class': input_class})
        self.fields['new_password2'].widget.attrs.update({'class': input_class})