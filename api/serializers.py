from rest_framework import routers, serializers, viewsets
from course.models import Courses, Category

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
