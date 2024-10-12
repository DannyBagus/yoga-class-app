from ninja import ModelSchema
from .models import Courses, Category

class CategorySchame(ModelSchema):
    class Meta:
        model = Category
        fields = ('id', 'name')

class CoursesSchema(ModelSchema):
    category:  CategorySchame | None = None
    
    class Meta:
        model = Courses
        fields = ('name', 'category', 'topic', 'date', 'start', 'duration')