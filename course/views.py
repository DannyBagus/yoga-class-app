from typing import Any
from django.shortcuts import render, get_object_or_404
from course.models import Courses, Booking
from users.models import Credits
from django.views.generic import ListView
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta

class CourseListView(ListView):
    model = Courses
    template_name = 'course/courses.html'
    context_object_name = 'courses'
    
    def get_queryset(self):
        # Use the custom manager to get upcoming courses
        return Courses.upcoming_courses.upcoming()  # Get courses with date >= today
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        courses = context['courses']
        
        # Format the date and time for each course
        for course in courses:
            course.formatted_date = course.date.strftime('%d.%m.%Y')  # Format date as day.month.year
            course.formatted_time = course.start.strftime('%H:%M')    # Format time as hour:minute
            
        # Get the list of course IDs where the user has a booking
        if self.request.user.is_authenticated:
            booked_courses = Booking.objects.filter(user=self.request.user).values_list('course_id', flat=True)
            context['booked_courses'] = booked_courses
        else:
            context['booked_courses'] = []  # Empty list if user is not logged in
        
        return context
    

def filter_courses(request):
    filter_type = request.GET.get('filter', 'all')
    
    if filter_type == 'yoga':
        courses = Courses.objects.filter(category__name='Yoga')
    elif filter_type == 'pilates':
        courses = Courses.objects.filter(category__name='Pilates')
    elif filter_type == 'my_courses':
        courses = Courses.objects.filter(bookings__user=request.user)
    else:
        courses = Courses.upcoming_courses.upcoming()
        
    # Format date and time for each course
    formatted_courses = []
    for course in courses:
        course.formatted_date = course.date.strftime('%d.%m.%Y')  # Format date as day.month.year
        course.formatted_time = course.start.strftime('%H:%M')    # Format time as hour:minute
        formatted_courses.append(course)
    
    # Get course IDs where the user has a booking
    booked_courses = Booking.objects.filter(user=request.user).values_list('course_id', flat=True)
                       
    context = {
        'courses': courses,
        'booked_courses': booked_courses
    }
        
    return render(request, 'partials/course_list.html', context)


def create_booking(request):
    course_id = request.GET.get('course')
    if course_id:
        course = Courses.objects.filter(pk=course_id).first()
        if course:
            if request.user.is_authenticated:
                try:
                    # Get user's credits
                    user_credits = Credits.objects.get(user=request.user)
                    
                    if user_credits.number > 0:
                        # Reduce credits by 1
                        user_credits.number -= 1
                        user_credits.save()

                        # Create the booking
                        Booking.objects.get_or_create(user=request.user, course=course)
                        
                        # Reduce course capacity
                        course.capacity = max(course.capacity - 1, 0)
                        course.save()
                        messages.success(request, f"Buchung erfolgreich. Du hast {user_credits.number} Credit(s) übrig.")
                    else:
                        # Handle no credits
                        messages.error(request, "Du hast nicht genügend Credits.")
                
                except Credits.DoesNotExist:
                    messages.error(request, "Du hast noch keine Credits gekauft.")
    
    courses = Courses.upcoming_courses.upcoming()
    
    # Format the date and time for each course
    for course in courses:
        course.formatted_date = course.date.strftime('%d.%m.%Y')  # Format date as day.month.year
        course.formatted_time = course.start.strftime('%H:%M')    # Format time as hour:minute
    
    # Get course IDs where the user has a booking
    booked_courses = Booking.objects.filter(user=request.user).values_list('course_id', flat=True)
                       
    context = {
        'courses': courses,
        'booked_courses': booked_courses
    }
        
    return render(request, 'partials/course_list.html', context)


def cancel_booking(request):
    if request.method == 'GET':
        course_id = request.GET.get('course')
        course = get_object_or_404(Courses, pk=course_id)
        
        # Check if the user has an existing booking for the course
        booking = Booking.objects.filter(user=request.user, course=course).first()

        if booking:
            # Course start time
            course_start_time = timezone.make_aware(datetime.combine(course.date, course.start))

            # Check if the course starts in more than 24 hours
            if course_start_time - timezone.now() > timezone.timedelta(hours=24):
                # Add credit back to user's balance
                credits, created = Credits.objects.get_or_create(user=request.user)
                credits.number += 1  # Assuming each booking gives 1 credit
                credits.save()

                # Optionally delete the booking
                booking.delete()
                messages.success(request, f"Du wurdest erfolgreich abgemeldet. Du hast {credits.number} Credit(s) übrig.")
                
            else:
                # Optionally delete the booking without adding credit
                booking.delete()
                messages.success(request, "Du wurdest erfolgreich abgemeldet. Die Abmeldefrist wurde nicht eingehalten. Du hast {credits.number} Credit(s) übrig.")
                            
            # Increase course capacity
            course.capacity = min(course.capacity + 1, 7)
            course.save()
            
        else:
            # Handle case where no booking exists
            messages.error(request, "Es wurde keine Buchung gefunden.")

        # Render the updated courses list after booking cancellation
        courses = Courses.objects.all()
        
        # Format the date and time for each course
        for course in courses:
            course.formatted_date = course.date.strftime('%d.%m.%Y')  # Format date as day.month.year
            course.formatted_time = course.start.strftime('%H:%M')    # Format time as hour:minute
            
        # Get course IDs where the user has a booking
        booked_courses = Booking.objects.filter(user=request.user).values_list('course_id', flat=True)
        
    context = {
        'courses': courses,
        'booked_courses': booked_courses
    }
        
    return render(request, 'partials/course_list.html', context)