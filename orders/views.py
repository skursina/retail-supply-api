from .models import Address
from .serializers import AddressSerializer


class AddressListCreateView(generics.ListCreateAPIView):
    """Список и создание адресов покупателя."""
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Address.objects.filter(buyer=self.request.user)


class AddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Просмотр, изменение и удаление адреса."""
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Address.objects.filter(buyer=self.request.user)