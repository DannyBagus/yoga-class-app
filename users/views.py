from django.shortcuts import render, redirect
from .forms import CustomUserCreationForm, CustomAuthenticateForm, PhoneForm
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordResetView
from django.contrib.sites.shortcuts import get_current_site
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from urllib.parse import urlencode
from core.models import News
from users.models import Credits, PurchaseTransaction, Profile
from course.models import Booking

def _safe_next_url(request, url):
    ''' Rueckspruengziel nur innerhalb dieser Seite zulassen (kein Open Redirect) '''
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return ''

def register_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False # Deactivates account until it is confirmed
            user.save()
            Profile.objects.update_or_create(user=user, defaults={'phone': form.cleaned_data['phone']})
            
            # Send verification email
            current_site = get_current_site(request)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            protocol = 'https' if request.is_secure() else 'http'
            activation_url = f'{protocol}://{current_site.domain}/users/activate/{uid}/{token}'

            mail_subject = 'Bestätige Deine Registrierung beim Mileja Yoga & Pilates.'
            context = {'user': user, 'activation_url': activation_url}
            html_message = render_to_string('users/activation_email.html', context)
            text_message = render_to_string('users/activation_email.txt', context)
            to_email = form.cleaned_data.get('email')
            send_mail(
                mail_subject,
                text_message,
                'admin@mileja.ch',
                [to_email],
                fail_silently=False,
                html_message=html_message
            )
            
            return render(request, "users/registration_complete.html")
    else:
        form = CustomUserCreationForm()
    return render(request, "users/register.html", { "form": form })

def logout_user(request):
    logout(request)
    return redirect('home')

def login_user(request):
    if request.method == 'POST':

        identifier = request.POST['username'].strip()
        password = request.POST['password']
        # Erlaube Login per Username oder E-Mail
        if '@' in identifier:
            user_obj = User.objects.filter(email__iexact=identifier).first()
            username = user_obj.username if user_obj else identifier
        else:
            username = identifier
        user = authenticate(request, username=username, password=password)
        next_url = _safe_next_url(request, request.POST.get('next'))
        if user is not None:
            login(request, user)
            return redirect(next_url or 'my-account')
            
        else:
            messages.error(request, ("Du konntest nicht angemeldet werden. Versuche es erneut..."))
            if next_url:
                return redirect(f"{reverse('login')}?{urlencode({'next': next_url})}")
            return redirect('login')
    else:
        form = CustomAuthenticateForm()
        next_url = _safe_next_url(request, request.GET.get('next'))
        
        return render(request, 'users/login.html', { "form": form, "next": next_url })
    
def activate(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except(TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        # Mehrere AUTHENTICATION_BACKENDS sind aktiv (OIDC + ModelBackend).
        # Der User stammt aus User.objects.get() und hat kein .backend-Attribut,
        # daher muss das Backend explizit angegeben werden, sonst wirft login()
        # einen ValueError -> 500.
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return render(request, 'users/confirmation_successful.html')
    else:
        return render(request, 'users/activation_invalid.html')

class CustomPasswordResetView(PasswordResetView):
    html_email_template_name = "users/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email, html_email_template_name=None, **kwargs):
        subject = render_to_string(subject_template_name, context)
        subject = ''.join(subject.splitlines())  # Remove newlines

        # Render your HTML email template
        message = render_to_string(html_email_template_name or email_template_name, context)

        # Send the email
        send_mail(
            subject,
            '',  # No plain text message since we're using HTML
            from_email,
            [to_email],
            fail_silently=False,
            html_message=message  # Use the rendered HTML
        )
    
@login_required
def phone_view(request):
    """Natelnummer erfassen/aendern.

    Die RequirePhoneMiddleware leitet jeden User ohne Nummer hierher um; die
    Seite hat bewusst keinen Abbrechen-Weg (nur Speichern oder Logout).
    """
    profile, _ = Profile.objects.get_or_create(user=request.user)
    next_url = _safe_next_url(request, request.POST.get('next') or request.GET.get('next'))

    if request.method == 'POST':
        form = PhoneForm(request.POST)
        if form.is_valid():
            profile.phone = form.cleaned_data['phone']
            profile.save(update_fields=['phone'])
            messages.success(request, "Danke! Deine Natelnummer wurde gespeichert.")
            return redirect(next_url or 'my-account')
    else:
        form = PhoneForm(initial={'phone': profile.phone})

    return render(request, 'users/phone.html', {
        'form': form,
        'next': next_url,
        'is_required': not profile.phone,
    })

def my_account(request):
    nav_content = request.GET.get('navigate')
    
    if nav_content == 'news':      
        news = News.objects.filter(publish_date__lte=timezone.now()).order_by('-publish_date')  
        context = {
            "news": news
        }
        
        return render(request, 'partials/news_list.html', context)
    
    if nav_content == 'credits':   
        user = request.user
        ''' get number of credits the user has '''
        credits = Credits.objects.get(user=user)
            
        ''' get purchase history of user'''
        purchase_transactions = PurchaseTransaction.objects.filter(user=user).order_by('-date')

        context = {
            "credits": credits.number,
            "purchase_transactions": purchase_transactions
        }
        return render(request, 'partials/my_credits.html', context)
    
    if nav_content == 'bookings':
        user = request.user
        ''' get bookings of logged-in user '''
        bookings = Booking.objects.filter(user=user).order_by('-course__date')
        
        # Format the time for each booking
        for booking in bookings:
            booking.course_time = booking.course.start.strftime('%H:%M')  # Format course start time
            
        context = {
            "bookings": bookings
        }
        
        return render(request, 'partials/my_bookings.html', context)
    
    if nav_content == 'gtc':      
        return render(request, 'partials/gtc.html')
    
    phone = Profile.objects.filter(user=request.user).values_list('phone', flat=True).first() if request.user.is_authenticated else ''
    return render(request, 'users/my_account.html', {'phone': phone})
    

def news_item(request):
    news_item_id = request.GET.get('item')
    news_item = News.objects.get(pk=news_item_id)
    return render(request, 'partials/news_item.html', {"news_item": news_item})

def gtc_full(request):
    return render(request, 'users/gtc_base.html')

def dsg(request):
    return render(request, 'users/dsg.html')

def purchase_credits(request):
    """Legacy-URL: leitet auf Mein Konto weiter (Stripe hat uebernommen)."""
    return redirect('my-account')
    