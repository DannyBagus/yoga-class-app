from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('activate/<uidb64>/<token>/', views.activate, name='activate'),
    path('logout/', views.logout_user, name='logout'),
    path('login/', views.login_user, name='login'),
    path('mein-konto/', views.my_account, name='my-account'),
    path('news/', views.news_item, name='news-item'),
    path('purchase-credits/', views.purchase_credits, name='confirm-purchase'),
    path('agb/', views.gtc_full, name='gtc-full')
]