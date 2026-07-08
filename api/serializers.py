from rest_framework import routers, serializers, viewsets
from course.models import Courses, Category, Booking

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'

class CoursesSerializer(serializers.ModelSerializer):
    category = CategorySerializer(many=False, read_only=True)
    date = serializers.DateField(format="%d.%m.%Y")
    start = serializers.TimeField(format="%H:%M")
    
    class Meta:
        model = Courses
        fields = '__all__'

class UserBookingSerializer(serializers.ModelSerializer):
    ''' eine einzelne Buchung einer Kundin, angereichert mit Kursinfos '''
    category = serializers.CharField(source='course.category.name', read_only=True)
    course_name = serializers.CharField(source='course.name', read_only=True)
    topic = serializers.CharField(source='course.topic', read_only=True)
    date = serializers.DateField(source='course.date', format="%d.%m.%Y", read_only=True)
    start = serializers.TimeField(source='course.start', format="%H:%M", read_only=True)
    duration = serializers.IntegerField(source='course.duration', read_only=True)
    booked_at = serializers.DateTimeField(source='date', format="%d.%m.%Y %H:%M", read_only=True)

    class Meta:
        model = Booking
        fields = ['category', 'course_name', 'topic', 'date', 'start', 'duration', 'booked_at']
