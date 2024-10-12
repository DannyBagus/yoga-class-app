from django.shortcuts import render, redirect
from .forms import CustomUserCreationForm, CustomAuthenticateForm
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from core.models import News
from users.models import Credits, PurchaseTransaction

def register_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False # Deactivates account until it is confirmed
            user.save()
            
            # Send verification email
            current_site = get_current_site(request)
            mail_subject = 'Bestätige Deine Registrierung beim Mileja Yoga & Pilates.'
            message = render_to_string('users/activation_email.html', {
                'user': user,
                'domain': current_site.domain,
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'token': default_token_generator.make_token(user),
            })
            to_email = form.cleaned_data.get('email')
            send_mail(mail_subject, message, 'admin@mileja.ch', [to_email])
            
            return render(request, "users/registration_complete.html")
    else:
        form = CustomUserCreationForm()
    return render(request, "users/register.html", { "form": form })

def logout_user(request):
    logout(request)
    messages.success(request, ("Du wurdest erfolgreich ausgeloggt!"))
    return redirect('home')

def login_user(request):
    if request.method == 'POST':

        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        next = request.POST.get('next', '/')
        if user is not None:
            login(request, user)
            if next:
                return redirect(next)
            else:
                return redirect('home')
            
        else:
            messages.success(request, ("Du konntest nicht angemeldet werden. Versuche es erneut..."))
            return redirect('users:login')
    else:
        form = CustomAuthenticateForm()
        
        return render(request, 'users/login.html', { "form": form })
    
def activate(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except(TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        login(request, user)
        return redirect('home')
    else:
        return render(request, 'registration/activation_invalid.html')
    
    
def my_account(request):
    nav_content = request.GET.get('navigate')
    
    if nav_content == 'news':      
        news = News.objects.filter(publish_date__lte=timezone.now())        
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
        return render(request, 'partials/my_bookings.html')
    
    if nav_content == 'gtc':      
        return render(request, 'partials/gtc.html')
    
    return render(request, 'users/my_account.html')
    

def news_item(request):
    news_item_id = request.GET.get('item')
    news_item = News.objects.get(pk=news_item_id)
    return render(request, 'partials/news_item.html', {"news_item": news_item})

def purchase_credits(request):
    user = request.user
    
    # Get the number of credits from the POST data
    number = request.GET.get('number')
    
    # Create a new PurchaseTransaction
    purchase = PurchaseTransaction(
        user=request.user,  # Assign the current logged-in user
        number=number,  # Set the number of credits
        date=timezone.now()  # Set the transaction date
    )
    purchase.save()
    
    # send mail to back office
    mail_subject = 'ACTION REQUIRED: Kauf Credits'
    message = render_to_string('users/mail_purchase_transaction.html', {
        'user': user,
        'number': number
    })
    send_mail(mail_subject, message, 'admin@mileja.ch', ['admin@mileja.ch'])
    
    # render transactions-partials        
    ''' get purchase history of user'''
    purchase_transactions = PurchaseTransaction.objects.filter(user=user).order_by('-date')

    context = {
        "purchase_transactions": purchase_transactions
    }
    return render(request, 'partials/transaction_history.html', context)
    
    