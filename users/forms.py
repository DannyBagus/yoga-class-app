import time
from typing import Any
from django import forms
from django.core import signing
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordResetForm, SetPasswordForm

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    # --- Bot-Schutz ---------------------------------------------------------
    # Honeypot: echte Nutzer sehen dieses Feld nicht (CSS-versteckt im Template)
    # und lassen es leer. Bots fuellen blind alle Felder aus -> Reject.
    website = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'tabindex': '-1'}),
        label='',
    )
    # Signierte Zeit-Falle: Beim GET wird ein signierter Zeitstempel eingebettet.
    # Submits, die unrealistisch schnell (< MIN_FILL_SECONDS) ankommen, sind Bots.
    form_ts = forms.CharField(required=False, widget=forms.HiddenInput())

    MIN_FILL_SECONDS = 3
    SPAM_ERROR = "Deine Anfrage konnte nicht verarbeitet werden. Bitte versuche es erneut."

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        input_class = "w-full rounded-lg p-3 mb-2 text-black bg-white border border-gray-300 focus:ring-2 focus:ring-[#e46aeb] focus:border-transparent focus:outline-none"
        for field_name in ('username', 'email', 'first_name', 'last_name', 'password1', 'password2'):
            self.fields[field_name].widget.attrs['class'] = input_class

        # Frischen signierten Zeitstempel nur fuer das Render (ungebundenes Formular)
        if not self.is_bound:
            self.fields['form_ts'].initial = signing.dumps(time.time())

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Diese E-Mail Adresse ist bereits registriert.")
        return email

    def clean(self):
        cleaned = super().clean()
        # Honeypot muss leer sein.
        if self.data.get('website'):
            raise forms.ValidationError(self.SPAM_ERROR)
        # Zeit-Falle pruefen.
        try:
            started = signing.loads(self.data.get('form_ts', ''), max_age=86400)
            if time.time() - float(started) < self.MIN_FILL_SECONDS:
                raise forms.ValidationError(self.SPAM_ERROR)
        except (signing.BadSignature, signing.SignatureExpired, TypeError, ValueError):
            raise forms.ValidationError(self.SPAM_ERROR)
        return cleaned

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