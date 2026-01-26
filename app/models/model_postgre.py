from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.schema import FetchedValue
from app.services.postgre_client import Base

class Class(Base):
    __tablename__ = "class"
    class_id = Column(String, primary_key=True, index=True, server_default=FetchedValue())
    class_name = Column(String)
    mongo_id = Column(String)
    __mapper_args__ = {"eager_defaults": True}

class Subject(Base):
    __tablename__ = "subject"
    subject_id = Column(String, primary_key=True, index=True, server_default=FetchedValue())
    subject_name = Column(String)
    subject_type = Column(String)
    mongo_id = Column(String)
    class_id = Column(String, ForeignKey("class.class_id"))
    __mapper_args__ = {"eager_defaults": True}

class Topic(Base):
    __tablename__ = "topic"
    topic_id = Column(String, primary_key=True, index=True, server_default=FetchedValue())
    topic_num = Column(String)
    topic_name = Column(String)
    mongo_id = Column(String)
    subject_id = Column(String, ForeignKey("subject.subject_id"))
    __mapper_args__ = {"eager_defaults": True}

class Lesson(Base):
    __tablename__ = "lesson"
    lesson_id = Column(String, primary_key=True, index=True, server_default=FetchedValue())
    lesson_num = Column(String)
    lesson_name = Column(String)
    lesson_type = Column(String)
    mongo_id = Column(String)
    topic_id = Column(String, ForeignKey("topic.topic_id"))
    __mapper_args__ = {"eager_defaults": True}

class Chunk(Base):
    __tablename__ = "chunk"
    chunk_id = Column(String, primary_key=True, index=True, server_default=FetchedValue())
    chunk_label = Column(String)
    chunk_name = Column(String)
    mongo_id = Column(String)
    lesson_id = Column(String, ForeignKey("lesson.lesson_id"))
    __mapper_args__ = {"eager_defaults": True}

class Keyword(Base):
    __tablename__ = "keyword"
    keyword_id = Column(String, primary_key=True, index=True)  # (chưa có trigger nên giữ nguyên)
    keyword_name = Column(String)
    mongo_id = Column(String)
    chunk_id = Column(String, ForeignKey("chunk.chunk_id"))

class User(Base):
    __tablename__ = "user"
    user_id = Column(String, primary_key=True, index=True, server_default=FetchedValue())
    username = Column(String)
    password = Column(String)
    user_role = Column(String)
    mongo_id = Column(String)
    __mapper_args__ = {"eager_defaults": True}
