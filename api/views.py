from typing import Any
from rest_framework import generics
from course.models import Courses
from .serializers import CoursesSerializer

class CoursesListView(generics.ListAPIView):
    queryset = Courses.objects.all()
    serializer_class = CoursesSerializer
    
