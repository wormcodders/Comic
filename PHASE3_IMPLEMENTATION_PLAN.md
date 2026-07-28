# Phase 3 Implementation Plan: Social Features

## Overview
This document details the implementation of Phase 3 features for ComicVault, focusing on social interaction features including comments, reading lists, and activity feeds.

## Phase 3 Features

### 3.1 Comments System ⏳
- [ ] Add Comment database model
- [ ] Create comments table migration
- [ ] Implement comment CRUD API endpoints
- [ ] Add comment threading (replies)
- [ ] Create comment moderation system
- [ ] Add spoiler tags functionality
- [ ] Implement like/upvote for comments
- [ ] Add report inappropriate content feature
- [ ] Create comments UI component
- [ ] Add comments section to comic detail page
- [ ] Implement real-time comment updates

**Files to Create/Modify:**
- `models.py` - Add Comment model
- `routes.py` - Add comment API endpoints
- `templates/components/comments.html` - New comment component
- `templates/comic_detail.html` - Add comments section
- `static/css/main.css` - Add comment styles
- `static/js/comments.js` - New comment interaction JS

### 3.2 Reading Lists ⏳
- [ ] Add ReadingList database model
- [ ] Add ReadingListItem database model
- [ ] Create reading lists table migration
- [ ] Implement reading list CRUD API
- [ ] Add public/private list visibility
- [ ] Create "Follow" reading list functionality
- [ ] Implement "Staff Picks" curated lists
- [ ] Create reading list management UI
- [ ] Add reading list to user profile
- [ ] Create reading list detail page

**Files to Create/Modify:**
- `models.py` - Add ReadingList and ReadingListItem models
- `routes.py` - Add reading list endpoints
- `templates/user/reading_lists.html` - New template
- `templates/user/reading_list_detail.html` - New template
- `static/css/main.css` - Add reading list styles
- `templates/user/profile.html` - Add reading lists section

### 3.3 Activity Feed ⏳
- [ ] Add Activity database model
- [ ] Create activity tracking system
- [ ] Implement recently read activity sharing
- [ ] Add new chapter notifications
- [ ] Create following/followers system
- [ ] Implement activity feed API
- [ ] Create activity feed UI component
- [ ] Add activity feed to home page
- [ ] Implement activity privacy settings

**Files to Create/Modify:**
- `models.py` - Add Activity and Follow models
- `routes.py` - Add activity feed endpoints
- `templates/components/activity_feed.html` - New component
- `templates/home.html` - Add activity section
- `static/css/main.css` - Add activity feed styles
- `static/js/activity.js` - New activity JS

## Database Schema Additions

### Comment Model
```python
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    content = db.Column(db.Text, nullable=False)
    is_spoiler = db.Column(db.Boolean, default=False)
    is_hidden = db.Column(db.Boolean, default=False)
    likes_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### CommentLike Model
```python
class CommentLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

### ReadingList Model
```python
class ReadingList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    is_public = db.Column(db.Boolean, default=True)
    is_staff_pick = db.Column(db.Boolean, default=False)
    likes_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### ReadingListItem Model
```python
class ReadingListItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reading_list_id = db.Column(db.Integer, db.ForeignKey('reading_list.id'), nullable=False)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    order = db.Column(db.Integer, default=0)
```

### Activity Model
```python
class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)  # 'read', 'favorite', 'rating', 'comment'
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=True)
    data = db.Column(db.JSON)  # Additional activity data
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

### Follow Model
```python
class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    following_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

## API Endpoints

### Comments
```
GET    /api/comics/<id>/comments          - Get comments for comic
POST   /api/comics/<id>/comments          - Add comment to comic
PUT    /api/comments/<id>                 - Update comment
DELETE /api/comments/<id>                 - Delete comment
POST   /api/comments/<id>/like            - Like/unlike comment
POST   /api/comments/<id>/report          - Report comment
GET    /api/comments/<id>/replies         - Get comment replies
```

### Reading Lists
```
GET    /api/reading-lists                 - Get user's reading lists
POST   /api/reading-lists                 - Create new reading list
GET    /api/reading-lists/<id>            - Get reading list details
PUT    /api/reading-lists/<id>            - Update reading list
DELETE /api/reading-lists/<id>            - Delete reading list
POST   /api/reading-lists/<id>/items      - Add comic to list
DELETE /api/reading-lists/<id>/items/<id>  - Remove comic from list
POST   /api/reading-lists/<id>/follow     - Follow reading list
GET    /api/reading-lists/staff-picks     - Get staff picks
GET    /api/reading-lists/public          - Get public reading lists
```

### Activity Feed
```
GET    /api/activity                      - Get user's activity feed
GET    /api/activity/global               - Get global activity feed
POST   /api/users/<id>/follow             - Follow/unfollow user
GET    /api/users/<id>/followers          - Get user's followers
GET    /api/users/<id>/following          - Get users being followed
```

## UI Components

### 1. Comments Section
- Threaded comment display
- Reply input with @mentions
- Spoiler blur overlay
- Like/upvote button
- Report button
- Edit/delete options for author
- Sort options (newest, most liked)

### 2. Reading List Card
- Cover image grid preview
- Title and description
- Public/private badge
- Follower count
- "Follow" button for public lists
- Author avatar and name

### 3. Activity Feed Item
- User avatar and action
- Comic cover thumbnail
- Timestamp
- Activity type icon
- Privacy indicator

### 4. Follow Button
- Follow/unfollow toggle
- Follower count display
- Loading state

## Testing Strategy

### Unit Tests
- Comment CRUD operations
- Reading list management
- Activity tracking
- Follow/unfollow logic
- Permission checks

### Integration Tests
- Full comment flow
- Reading list creation and population
- Activity feed generation
- Following/followers system

### Manual Testing
- Mobile comment threading
- Spoiler tag functionality
- Reading list privacy settings
- Activity feed real-time updates

## Success Criteria
- [ ] Users can post comments on comics
- [ ] Comments support threading/replies
- [ ] Spoiler tags hide content until clicked
- [ ] Comment likes/upvotes functional
- [ ] Report system works for inappropriate content
- [ ] Users can create reading lists
- [ ] Reading lists can be public or private
- [ ] Users can follow other users' public lists
- [ ] Staff picks section displays curated lists
- [ ] Activity feed shows recent actions
- [ ] Following system connects users
- [ ] All features mobile-responsive

## Estimated Timeline
- **Day 1**: Database models and migrations
- **Day 2**: Comments system backend + basic UI
- **Day 3**: Reading lists backend + UI
- **Day 4**: Activity feed + Following system
- **Day 5**: Polish, testing, and bug fixes

Total: 5 days

## Priority: Low
## Dependencies: Phase 1 and Phase 2 features
