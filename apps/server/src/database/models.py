from tortoise import fields, models


class Workspace(models.Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, index=True)
    client_name = fields.CharField(max_length=255, index=True)
    tags = fields.JSONField(default=list)
    description = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    documents: fields.ReverseRelation["Document"]

    class Meta:
        table = "workspaces"

    def __str__(self) -> str:
        return self.name


class Document(models.Model):
    id = fields.IntField(pk=True)
    file_name = fields.CharField(max_length=512, index=True)
    file_size = fields.CharField(max_length=64, default="")
    page_count = fields.IntField(default=0)
    chunk_count = fields.IntField(default=0)
    uploaded_at = fields.DatetimeField(auto_now_add=True)
    workspace = fields.ForeignKeyField(
        "models.Workspace",
        related_name="documents",
        on_delete=fields.CASCADE,
    )

    chunks: fields.ReverseRelation["WorkspaceChunk"]

    class Meta:
        table = "documents"

    def __str__(self) -> str:
        return self.file_name


class WorkspaceChunk(models.Model):
    id = fields.IntField(pk=True)
    start_page = fields.IntField(null=True)
    end_page = fields.IntField(null=True)
    chunk_text = fields.TextField()
    document = fields.ForeignKeyField(
        "models.Document",
        related_name="chunks",
        on_delete=fields.CASCADE,
    )

    class Meta:
        table = "workspace_chunks"

    def __str__(self) -> str:
        return f"Chunk {self.id}"
