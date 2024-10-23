from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import CustomPasswordResetForm, CustomSetPasswordForm

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('activate/<uidb64>/<token>/', views.activate, name='activate'),
    path('logout/', views.logout_user, name='logout'),
    path('login/', views.login_user, name='login'),
    path('mein-konto/', views.my_account, name='my-account'),
    path('news/', views.news_item, name='news-item'),
    path('purchase-credits/', views.purchase_credits, name='confirm-purchase'),
    path('agb/', views.gtc_full, name='gtc-full'),
    path('dsg/', views.dsg, name='dsg'),
    path('password_reset/', views.CustomPasswordResetView.as_view(
        form_class=CustomPasswordResetForm,
        template_name='users/password_reset_form.html',
        email_template_name='users/password_reset_email.html' 
    ), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='users/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='users/password_reset_confirm.html',
        form_class=CustomSetPasswordForm
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='users/password_reset_complete.html'), name='password_reset_complete'),
]