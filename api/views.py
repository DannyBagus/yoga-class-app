from typing import Any
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from course.models import Courses, Booking
from users.models import Credits
from .permissions import HasWorkbenchApiKey
from .serializers import CoursesSerializer, UserBookingSerializer

class CoursesListView(generics.ListAPIView):
    queryset = Courses.objects.all()
    serializer_class = CoursesSerializer


class UserBookingsView(APIView):
    ''' Liefert Account-Infos und Buchungen einer Kundin anhand ihrer E-Mail.

    Read-only, geschuetzt per ``X-API-KEY`` (siehe HasWorkbenchApiKey).
    Wird von der Mileja-Workbench (Kunden-Detailseite) konsumiert.
    '''
    permission_classes = [HasWorkbenchApiKey]

    def get(self, request, email):
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return Response(
                {'detail': 'Keine Kundin mit dieser E-Mail gefunden.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            credits = user.credits.number
        except Credits.DoesNotExist:
            credits = 0

        bookings = list(
            Booking.objects
            .filter(user=user)
            .select_related('course', 'course__category')
        )
        # Sortierung: nach Kurstyp (Kategorie) aufsteigend, innerhalb desselben
        # Kurstyps chronologisch absteigend (neu zuoberst). Pythons stabiler Sort
        # erlaubt das durch zwei Durchgaenge (Datum zuerst, dann Kategorie).
        bookings.sort(key=lambda b: b.course.date, reverse=True)
        bookings.sort(key=lambda b: b.course.category.name.lower())

        admin_url = request.build_absolute_uri(
            reverse('admin:auth_user_change', args=[user.id])
        )

        data = {
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'credits': credits,
            'admin_url': admin_url,
            'bookings': UserBookingSerializer(bookings, many=True).data,
        }
        return Response(data)
