from django.shortcuts import render

def home(request):
    return render(request, 'core/home.html')

def yoga(request):
    return render(request, 'core/yoga.html')

def pilates(request):
    return render(request, 'core/pilates.html')

def impressum(request):
    return render(request, 'core/impressum.html')